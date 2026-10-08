"""Integration tests require an isolated, migrated PostgreSQL database ending in _test."""
import asyncio
import hashlib
import os
from io import BytesIO
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import routes
from app import vision_routes
from app.auth import create_access_token
from app.database import get_session
from app.domain import WorkOrderPriority, WorkOrderStatus, WorkOrderType
from app.main import app
from app.models import IdempotentAction, MaterialUsage, User, WorkOrder, WorkOrderCompletion, WorkOrderEvent, WorkOrderPhoto

TEST_URL = os.getenv("TEST_DATABASE_URL")


def test_jpeg(color='gray'):
    output=BytesIO()
    Image.new('RGB',(16,16),color).save(output,format='JPEG')
    return output.getvalue()


class DropFirstResponse(httpx.AsyncBaseTransport):
    """Let ASGI commit and produce its response, then simulate a lost HTTP reply."""
    def __init__(self):
        self.inner = httpx.ASGITransport(app=app)
        self.dropped = False
        self.committed_body = None

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if not self.dropped:
            self.dropped = True
            await response.aread()
            self.committed_body = response.json()
            await response.aclose()
            raise httpx.ReadError("Reply lost after server commit", request=request)
        return response

    async def aclose(self):
        await self.inner.aclose()


@unittest.skipUnless(TEST_URL, "Set TEST_DATABASE_URL to an isolated migrated PostgreSQL database")
class IdempotencyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(TEST_URL)
        if url.drivername != "postgresql+asyncpg" or not url.database.endswith("_test"):
            raise RuntimeError("Refusing a non-test database")
        self.engine = create_async_engine(TEST_URL, poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async def session_dependency():
            async with self.sessions() as session:
                yield session
        app.dependency_overrides[get_session] = session_dependency
        self.directory = tempfile.TemporaryDirectory()
        self.storage = patch.object(routes, "STORAGE_DIR", Path(self.directory.name))
        self.storage.start()
        self.broadcast = patch.object(routes.manager, "broadcast", new_callable=AsyncMock)
        self.broadcast_mock = self.broadcast.start()
        async with self.sessions() as session:
            self.worker_headers = {"Authorization": f"Bearer {create_access_token(await session.get(User, 2))}"}
            self.other_headers = {"Authorization": f"Bearer {create_access_token(await session.get(User, 3))}"}
            self.master_headers = {"Authorization": f"Bearer {create_access_token(await session.get(User, 1))}"}
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.order_id = await self.new_order()
        self.key = str(uuid4())

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        self.broadcast.stop()
        self.storage.stop()
        self.directory.cleanup()
        await self.engine.dispose()

    async def new_order(self, status=WorkOrderStatus.ISSUED):
        async with self.sessions() as session:
            order = WorkOrder(number=f"T-{uuid4().hex[:20]}", description="Test repair", work_type=WorkOrderType.PLANNED,
                site_id=1, equipment_id=1, assignee_id=2, master_id=1, priority=WorkOrderPriority.NORMAL,
                status=status, due_at=datetime.now(UTC) + timedelta(days=1))
            session.add(order)
            await session.commit()
            return order.id

    async def transition(self, key=None, status="accepted", order_id=None, headers=None):
        return await self.client.post(f"/api/work-orders/{order_id or self.order_id}/transitions",
            headers={**(headers or self.worker_headers), "Idempotency-Key": key or self.key}, json={"status": status})

    async def count(self, model, order_id=None):
        async with self.sessions() as session:
            query = select(func.count()).select_from(model)
            if hasattr(model, "work_order_id"):
                query = query.where(model.work_order_id == (order_id or self.order_id))
            elif model is IdempotentAction:
                query = query.where(model.key == self.key)
            return await session.scalar(query)

    async def test_lost_reply_replays_original_even_after_later_transition(self):
        transport = DropFirstResponse()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with self.assertRaises(httpx.ReadError):
                await client.post(f"/api/work-orders/{self.order_id}/transitions",
                    headers={**self.worker_headers, "Idempotency-Key": self.key}, json={"status": "accepted"})
        self.assertEqual((await self.transition(key=str(uuid4()), status="in_progress")).status_code, 200)
        repeated = await self.transition()
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json(), transport.committed_body)
        self.assertEqual(await self.count(WorkOrderEvent), 2)
        async with self.sessions() as session:
            self.assertEqual((await session.get(WorkOrder, self.order_id)).status, WorkOrderStatus.IN_PROGRESS)
        self.assertEqual(self.broadcast_mock.await_count, 2)

    async def test_concurrent_identical_transitions_execute_once(self):
        replies = await asyncio.gather(*[self.transition() for _ in range(5)])
        self.assertEqual([reply.status_code for reply in replies], [200] * 5)
        self.assertTrue(all(reply.json() == replies[0].json() for reply in replies))
        self.assertEqual(await self.count(WorkOrderEvent), 1)
        self.assertEqual(await self.count(IdempotentAction), 1)
        self.assertEqual(self.broadcast_mock.await_count, 1)

    async def test_reused_key_different_content_or_order_is_conflict(self):
        self.assertEqual((await self.transition()).status_code, 200)
        self.assertEqual((await self.transition(status="in_progress")).status_code, 409)
        other_id = await self.new_order()
        self.assertEqual((await self.transition(order_id=other_id)).status_code, 409)
        self.assertEqual(await self.count(WorkOrderEvent, other_id), 0)

    async def test_replay_still_requires_current_access(self):
        await self.transition()
        self.assertEqual((await self.transition(headers=self.other_headers)).status_code, 403)
        unauthenticated = await self.client.post(f"/api/work-orders/{self.order_id}/transitions",
            headers={"Idempotency-Key": self.key}, json={"status": "accepted"})
        self.assertEqual(unauthenticated.status_code, 401)

    async def test_invalid_key_or_action_does_not_leave_receipt(self):
        self.assertEqual((await self.transition(key="not-uuid")).status_code, 422)
        self.assertEqual((await self.transition(status="paused")).status_code, 409)
        self.assertEqual(await self.count(IdempotentAction), 0)
        self.assertEqual((await self.transition()).status_code, 200)

    async def complete(self, client=None, image=None, work="Replaced seal"):
        if image is None:
            image=test_jpeg()
        return await (client or self.client).post(f"/api/work-orders/{self.order_id}/complete",
            headers={**self.worker_headers, "Idempotency-Key": self.key},
            data={"work_performed": work, "fault_code_id": "1", "materials_json": '[{"material_id":1,"quantity":2}]'},
            files={"photo": ("after.jpg", image, "image/jpeg")})

    async def test_completion_lost_reply_does_not_duplicate_report_materials_or_photo(self):
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        transport = DropFirstResponse()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with self.assertRaises(httpx.ReadError):
                await self.complete(client)
        repeated = await self.complete()
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json(), transport.committed_body)
        for model in (WorkOrderCompletion, WorkOrderPhoto, WorkOrderEvent):
            self.assertEqual(await self.count(model), 1)
        async with self.sessions() as session:
            count = await session.scalar(select(func.count(MaterialUsage.id)).join(WorkOrderCompletion)
                .where(WorkOrderCompletion.work_order_id == self.order_id))
            self.assertEqual(count, 1)
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)
        self.assertEqual((await self.complete(image=b"different-photo")).status_code, 409)
        self.assertEqual((await self.complete(work="Different work")).status_code, 409)

    async def test_invalid_completion_image_has_no_side_effects(self):
        self.order_id=await self.new_order(WorkOrderStatus.IN_PROGRESS)
        response=await self.complete(image=b'<svg>not a JPEG</svg>')
        self.assertEqual(response.status_code,422)
        for model in (WorkOrderCompletion,WorkOrderPhoto,WorkOrderEvent,IdempotentAction):
            self.assertEqual(await self.count(model),0)
        self.assertFalse(list(Path(self.directory.name).iterdir()))
        self.broadcast_mock.assert_not_awaited()
        async with self.sessions() as session:
            self.assertEqual((await session.get(WorkOrder,self.order_id)).status,WorkOrderStatus.IN_PROGRESS)

    async def test_creation_uses_decoded_mime_and_extension_not_filename(self):
        import json
        output=BytesIO();Image.new('RGB',(16,16),'blue').save(output,format='PNG');data=output.getvalue()
        payload={'description':'Valid image test','work_type':'planned','site_id':1,'equipment_id':1,'assignee_id':2,'priority':'normal','due_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()}
        response=await self.client.post('/api/work-orders/with-photos',headers=self.master_headers,data={'payload':json.dumps(payload)},files={'photos':('../../bad.html',data,'application/octet-stream')})
        self.assertEqual(response.status_code,201,response.text)
        created_id=response.json()['id']
        async with self.sessions() as session:
            photo=await session.scalar(select(WorkOrderPhoto).where(WorkOrderPhoto.work_order_id==created_id))
            self.assertEqual(photo.content_type,'image/png')
            self.assertEqual(Path(photo.file_path).suffix,'.png')
            self.assertTrue(Path(photo.file_path).is_relative_to(self.directory.name))
            self.assertEqual(Path(photo.file_path).read_bytes(),data)
            photo_id=photo.id
        served=await self.client.get(f'/api/work-orders/{created_id}/photos/{photo_id}/file',headers=self.master_headers)
        self.assertEqual(served.content,data)
        self.assertEqual(served.headers['content-type'],'image/png')
        self.assertEqual(served.headers['x-content-type-options'],'nosniff')

    async def test_invalid_creation_batch_or_total_limit_creates_nothing(self):
        import json
        payload={'description':'Invalid image test','work_type':'planned','site_id':1,'equipment_id':1,'assignee_id':2,'priority':'normal','due_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()}
        async with self.sessions() as session:
            before=await session.scalar(select(func.count(WorkOrder.id)))
        invalid=await self.client.post('/api/work-orders/with-photos',headers=self.master_headers,data={'payload':json.dumps(payload)},files=[('photos',('valid.jpg',test_jpeg(),'image/jpeg')),('photos',('fake.jpg',b'<html>fake</html>','image/jpeg'))])
        self.assertEqual(invalid.status_code,422)
        with patch.object(routes,'MAX_BATCH_BYTES',1024):
            oversized=await self.client.post('/api/work-orders/with-photos',headers=self.master_headers,data={'payload':json.dumps(payload)},files=[('photos',('first.jpg',test_jpeg(),'image/jpeg')),('photos',('second.jpg',test_jpeg(),'image/jpeg'))])
        self.assertEqual(oversized.status_code,413)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count(WorkOrder.id))),before)
        self.assertFalse(list(Path(self.directory.name).iterdir()))

    async def test_legacy_receipt_is_replayed_without_revalidating_old_image(self):
        from app.idempotency import request_hash
        from app.schemas import WorkOrderRead
        image=b'legacy-invalid-image'
        self.order_id=await self.new_order(WorkOrderStatus.COMPLETED)
        fingerprint=request_hash('completion',self.order_id,{'work_performed':'Replaced seal','fault_code_id':1,'comment':None,'materials':'[{"material_id":1,"quantity":2}]','photo':{'filename':'after.jpg','content_type':'image/jpeg','sha256':hashlib.sha256(image).hexdigest()}})
        async with self.sessions() as session:
            order=await session.get(WorkOrder,self.order_id)
            original=WorkOrderRead.model_validate(order).model_dump(mode='json')
            session.add(IdempotentAction(actor_id=2,key=self.key,request_hash=fingerprint,response_body=original))
            await session.commit()
        response=await self.complete(image=image)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),original)
        self.assertEqual(await self.count(IdempotentAction),1)
        self.assertEqual(await self.count(WorkOrderCompletion),0)

    async def test_completion_preserves_bytes_and_replay_skips_second_decode(self):
        output=BytesIO();Image.new('RGB',(16,16),'green').save(output,format='PNG');data=output.getvalue()
        self.order_id=await self.new_order(WorkOrderStatus.IN_PROGRESS)
        kwargs={'headers':{**self.worker_headers,'Idempotency-Key':self.key},'data':{'work_performed':'Valid PNG report','fault_code_id':'1'},'files':{'photo':('photo.html',data,'application/octet-stream')}}
        first=await self.client.post(f'/api/work-orders/{self.order_id}/complete',**kwargs)
        self.assertEqual(first.status_code,200,first.text)
        async with self.sessions() as session:
            photo=await session.scalar(select(WorkOrderPhoto).where(WorkOrderPhoto.work_order_id==self.order_id))
            self.assertEqual(photo.content_type,'image/png')
            self.assertEqual(Path(photo.file_path).suffix,'.png')
            self.assertEqual(Path(photo.file_path).read_bytes(),data)
        with patch.object(routes,'decode_photo',new_callable=AsyncMock,side_effect=AssertionError('Must replay before decoding')):
            repeated=await self.client.post(f'/api/work-orders/{self.order_id}/complete',**kwargs)
        self.assertEqual(repeated.status_code,200,repeated.text)
        self.assertEqual(repeated.json(),first.json())
        self.assertEqual(await self.count(WorkOrderCompletion),1)
        self.assertEqual(await self.count(WorkOrderPhoto),1)

    async def test_legacy_vector_file_is_not_served_inline(self):
        path=Path(self.directory.name)/'legacy.svg';path.write_bytes(b'<svg/>')
        async with self.sessions() as session:
            photo=WorkOrderPhoto(work_order_id=self.order_id,photo_type='before',file_path=str(path),original_name='legacy.svg',content_type='image/svg+xml',uploaded_by=1)
            session.add(photo);await session.commit();photo_id=photo.id
        response=await self.client.get(f'/api/work-orders/{self.order_id}/photos/{photo_id}/file',headers=self.master_headers)
        self.assertEqual(response.status_code,415)
        self.assertTrue(path.exists())
        self.assertEqual(await self.count(WorkOrderPhoto),1)

    async def test_concurrent_identical_completions_execute_once(self):
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        replies = await asyncio.gather(*[self.complete() for _ in range(3)])
        self.assertEqual([reply.status_code for reply in replies], [200] * 3)
        self.assertEqual(await self.count(WorkOrderCompletion), 1)
        self.assertEqual(await self.count(WorkOrderPhoto), 1)
        self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)

    async def test_failure_before_commit_rolls_back_effects_and_allows_retry(self):
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        async def fail(session, *args):
            raise RuntimeError("Database failure before commit")
        with patch.object(routes, "commit_action", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "before commit"):
                await self.complete()
        self.assertEqual(await self.count(WorkOrderCompletion), 0)
        self.assertEqual(await self.count(WorkOrderEvent), 0)
        self.assertEqual(await self.count(IdempotentAction), 0)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])
        self.assertEqual((await self.complete()).status_code, 200)

    async def test_rework_preserves_versions_and_requires_fresh_inspection(self):
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        first_key = self.key
        self.assertEqual((await self.complete(work="Replaced seal first time")).status_code, 200)
        first_review = await self.client.post(f"/api/work-orders/{self.order_id}/ai-review", headers=self.master_headers)
        self.assertEqual(first_review.status_code, 200)
        missing_reason = await self.client.post(f"/api/work-orders/{self.order_id}/transitions", headers=self.master_headers, json={"status":"rework", "comment":"  "})
        self.assertEqual(missing_reason.status_code, 422)
        rejected = await self.client.post(f"/api/work-orders/{self.order_id}/transitions", headers=self.master_headers, json={"status":"rework", "comment":"Устранить следы жидкости и приложить новый снимок"})
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual((await self.transition(key=str(uuid4()), status="in_progress")).status_code, 200)
        self.key = str(uuid4())
        self.assertEqual((await self.complete(work="Replaced seal and checked again", image=test_jpeg('blue'))).status_code, 200)
        self.assertEqual((await self.complete(work="Replaced seal and checked again", image=test_jpeg('blue'))).status_code, 200)
        report = (await self.client.get(f"/api/work-orders/{self.order_id}/report", headers=self.master_headers)).json()
        self.assertEqual(len(report["completions"]), 2)
        self.assertEqual(report["completion"]["work_performed"], "Replaced seal and checked again")
        self.assertEqual(report["completions"][0]["work_performed"], "Replaced seal first time")
        self.assertIsNone(report["inspection"])
        self.assertNotEqual(report["photos"][0]["completion_id"], report["photos"][1]["completion_id"])
        self.assertEqual(report["completions"][0]["materials"][0]["quantity"], 2)
        self.assertIsNone((await self.client.get(f"/api/work-orders/{self.order_id}/ai-review", headers=self.master_headers)).json())
        latest_reviews = (await self.client.get("/api/ai-reviews", headers=self.master_headers)).json()
        self.assertNotIn(self.order_id, [item["work_order_id"] for item in latest_reviews])
        second_review = await self.client.post(f"/api/work-orders/{self.order_id}/ai-review", headers=self.master_headers)
        self.assertEqual(second_review.status_code, 200)
        self.assertNotEqual(first_review.json()["id"], second_review.json()["id"])
        ratings = await self.client.get("/api/reports/ratings", headers=self.master_headers)
        self.assertEqual(ratings.status_code, 200)
        closed = await self.transition(key=str(uuid4()), status="closed", headers=self.master_headers)
        self.assertEqual(closed.status_code, 200)
        self.key = first_key
        self.assertEqual((await self.complete(work="Replaced seal first time")).status_code, 200)
        self.assertEqual(await self.count(WorkOrderCompletion), 2)
        self.assertEqual(await self.count(WorkOrderPhoto), 2)
        async with self.sessions() as session:
            self.assertEqual((await session.get(WorkOrder, self.order_id)).status, WorkOrderStatus.CLOSED)

    async def test_master_can_review_manually_without_ai(self):
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        self.assertEqual((await self.complete()).status_code, 200)
        worker_close = await self.transition(key=str(uuid4()), status="closed")
        self.assertEqual(worker_close.status_code, 403)
        self.assertEqual((await self.transition(key=str(uuid4()), status="closed", headers=self.master_headers)).status_code, 200)

    async def test_visual_analysis_is_advisory_and_version_scoped(self):
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        await self.complete()
        report = (await self.client.get(f"/api/work-orders/{self.order_id}/report", headers=self.master_headers)).json()
        completion_id = report["completion"]["id"]
        path = f"/api/work-orders/{self.order_id}/completions/{completion_id}/vision"
        result = {"observations":["Видно пятно"], "limitations":["Нельзя определить состав жидкости"], "needs_human_review":True}
        with patch.object(vision_routes.settings, "vlm_enabled", True), patch.object(vision_routes, "observe", new_callable=AsyncMock, return_value=result) as observe:
            self.assertEqual((await self.client.post(path, headers=self.worker_headers)).status_code, 403)
            first = await self.client.post(path, headers=self.master_headers)
            repeated = await self.client.post(path, headers=self.master_headers)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["status"], "done")
            self.assertEqual(first.json(), repeated.json())
            observe.assert_awaited_once()
        self.assertEqual(await self.count(WorkOrderEvent), 1)
        async with self.sessions() as session:
            self.assertEqual((await session.get(WorkOrder, self.order_id)).status, WorkOrderStatus.COMPLETED)
        revised = await self.client.post(f"/api/work-orders/{self.order_id}/transitions", headers=self.master_headers, json={"status":"rework", "comment":"Нужен новый снимок"})
        self.assertEqual(revised.status_code, 200)
        await self.transition(key=str(uuid4()), status="in_progress")
        self.key = str(uuid4())
        await self.complete(work="Second completion", image=test_jpeg('blue'))
        self.assertEqual((await self.client.post(path, headers=self.master_headers)).status_code, 409)
        report = (await self.client.get(f"/api/work-orders/{self.order_id}/report", headers=self.master_headers)).json()
        self.assertIsNone(report["completion"]["vision"])
        self.assertEqual(report["completions"][0]["vision"]["status"], "done")

    async def test_visual_error_is_saved_and_can_be_retried(self):
        from app.vision import VisionError
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        await self.complete()
        report = (await self.client.get(f"/api/work-orders/{self.order_id}/report", headers=self.master_headers)).json()
        path = f'/api/work-orders/{self.order_id}/completions/{report["completion"]["id"]}/vision'
        with patch.object(vision_routes.settings, "vlm_enabled", False):
            self.assertEqual((await self.client.post(path, headers=self.master_headers)).status_code, 503)
        with patch.object(vision_routes.settings, "vlm_enabled", True), patch.object(vision_routes, "observe", new_callable=AsyncMock, side_effect=VisionError("Модель недоступна")):
            failed = await self.client.post(path, headers=self.master_headers)
            self.assertEqual(failed.json()["status"], "failed")
        result = {"observations":[], "limitations":["Плохой ракурс"], "needs_human_review":True}
        with patch.object(vision_routes.settings, "vlm_enabled", True), patch.object(vision_routes, "observe", new_callable=AsyncMock, return_value=result):
            retried = await self.client.post(path, headers=self.master_headers)
            self.assertEqual(retried.json()["status"], "done")

    async def test_visual_running_request_is_not_duplicated(self):
        self.order_id = await self.new_order(WorkOrderStatus.IN_PROGRESS)
        await self.complete()
        report = (await self.client.get(f"/api/work-orders/{self.order_id}/report", headers=self.master_headers)).json()
        path = f'/api/work-orders/{self.order_id}/completions/{report["completion"]["id"]}/vision'
        started, release = asyncio.Event(), asyncio.Event()
        async def held_observe(photos):
            started.set()
            await release.wait()
            return {"observations":[],"limitations":["Плохой ракурс"],"needs_human_review":True}
        with patch.object(vision_routes.settings, "vlm_enabled", True), patch.object(vision_routes, "observe", side_effect=held_observe) as observe:
            first = asyncio.create_task(self.client.post(path, headers=self.master_headers))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                repeated = await self.client.post(path, headers=self.master_headers)
                self.assertEqual(repeated.json()["status"], "running")
                observe.assert_awaited_once()
            finally:
                release.set()
                await first
