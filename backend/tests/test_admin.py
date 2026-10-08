"""HTTP account-management checks on a disposable migrated PostgreSQL database."""
import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import bootstrap_admin
from app import main as main_module
from app.admin_routes import UserCreate
from app.auth import create_access_token, hash_pin
from app.database import get_session
from app.domain import UserRole, WorkOrderPriority, WorkOrderStatus, WorkOrderType
from app.main import app
from app.models import AdminAudit, User, WorkOrder
from app.realtime import ConnectionManager

TEST_URL = os.getenv('TEST_DATABASE_URL')


class RealtimeRevocationTest(unittest.IsolatedAsyncioTestCase):
    async def test_revocation_closes_only_target_connections(self):
        manager = ConnectionManager()
        a, b = AsyncMock(), AsyncMock()
        await manager.connect(a, 1)
        await manager.connect(b, 2)
        await manager.revoke_user(1)
        a.close.assert_awaited_once_with(code=4401)
        b.close.assert_not_awaited()
        self.assertEqual(manager.connections, {b})
        await manager.broadcast({'type':'test'})
        a.send_json.assert_not_awaited()


@unittest.skipUnless(TEST_URL, 'Set TEST_DATABASE_URL to an isolated migrated PostgreSQL database')
class AdminTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = make_url(TEST_URL)
        if url.drivername != 'postgresql+asyncpg' or not url.database.endswith('_test'):
            raise RuntimeError('Refusing a non-test database')
        self.engine = create_async_engine(TEST_URL, poolclass=NullPool)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async def dependency():
            async with self.sessions() as session:
                yield session
        app.dependency_overrides[get_session] = dependency
        self.users = {}
        self.created_ids = []
        self.headers = {}
        async with self.sessions() as session:
            for role in UserRole:
                user = User(login='test_'+uuid4().hex, full_name='Test '+role.value, role=role,
                            pin_hash=hash_pin('654321'), is_active=True, session_version=0)
                session.add(user)
                await session.flush()
                self.users[role.value] = user
                self.headers[role.value] = {'Authorization':'Bearer '+create_access_token(user)}
            await session.commit()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        async with self.sessions() as session:
            for user in self.users.values():
                stored = await session.get(User,user.id)
                stored.is_active = False
            for user_id in self.created_ids:
                (await session.get(User,user_id)).is_active = False
            await session.commit()
        await self.engine.dispose()

    def body(self, user, **changes):
        return {'full_name':user.full_name,'role':user.role.value,'specialty':user.specialty,
                'is_active':user.is_active,'expected_session_version':user.session_version,**changes}

    async def test_roles_cannot_manage_accounts_or_read_audit(self):
        self.assertEqual((await self.client.get('/api/admin/users')).status_code,401)
        for role in ['worker','master','manager']:
            for path in ['/api/admin/users','/api/admin/audit']:
                self.assertEqual((await self.client.get(path,headers=self.headers[role])).status_code,403)
            response = await self.client.put('/api/admin/users/'+str(self.users['worker'].id),headers=self.headers[role],json=self.body(self.users['worker']))
            self.assertEqual(response.status_code,403)

    async def test_create_all_roles_and_safe_case_insensitive_duplicates(self):
        for role in UserRole:
            login = 'new_'+uuid4().hex
            body={'login':login.upper(),'pin':'876543','full_name':'New account','role':role.value}
            response=await self.client.post('/api/admin/users',headers=self.headers['admin'],json=body)
            self.assertEqual(response.status_code,201,response.text)
            self.assertEqual(response.json()['login'],login)
            self.created_ids.append(response.json()['id'])
            self.assertNotIn('pin',response.text)
            self.assertNotIn('876543',response.text)
            duplicate=await self.client.post('/api/admin/users',headers=self.headers['admin'],json=body)
            self.assertEqual(duplicate.status_code,409)
            token=await self.client.post('/api/auth/login',json={'login':login.upper(),'pin':'876543'})
            self.assertEqual(token.status_code,200)
            self.assertEqual(token.json()['user']['role'],role.value)

    async def test_invalid_credentials_are_not_echoed(self):
        response=await self.client.post('/api/admin/users',headers=self.headers['admin'],json={'login':'bad account','pin':'secret-pin-value','full_name':'Valid Name','role':'worker'})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('secret-pin-value',response.text)

    async def test_block_revokes_token_and_hides_from_assignment_directories(self):
        user=self.users['worker']
        with patch('app.admin_routes.manager.revoke_user',new_callable=AsyncMock) as revoke:
            response=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,is_active=False))
            self.assertEqual(response.status_code,200,response.text)
            revoke.assert_awaited_once_with(user.id)
        self.assertEqual((await self.client.get('/api/auth/me',headers=self.headers['worker'])).status_code,401)
        self.assertEqual((await self.client.post('/api/auth/login',json={'login':user.login,'pin':'654321'})).status_code,401)
        directories=(await self.client.get('/api/directories',headers=self.headers['admin'])).json()
        self.assertNotIn(user.id,[item['id'] for item in directories['users']])
        current=response.json()
        unblocked=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,is_active=True,expected_session_version=current['session_version']))
        self.assertEqual(unblocked.status_code,200)
        self.assertEqual((await self.client.get('/api/auth/me',headers=self.headers['worker'])).status_code,401)
        self.assertEqual((await self.client.post('/api/auth/login',json={'login':user.login,'pin':'654321'})).status_code,200)

    async def test_reset_pin_revokes_old_token_and_does_not_record_secret(self):
        user=self.users['worker']
        response=await self.client.post(f'/api/admin/users/{user.id}/reset-pin',headers=self.headers['admin'],json={'pin':'876543','expected_session_version':0})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await self.client.get('/api/auth/me',headers=self.headers['worker'])).status_code,401)
        self.assertEqual((await self.client.post('/api/auth/login',json={'login':user.login,'pin':'654321'})).status_code,401)
        self.assertEqual((await self.client.post('/api/auth/login',json={'login':user.login,'pin':'876543'})).status_code,200)
        audit=(await self.client.get('/api/admin/audit',headers=self.headers['admin'])).text
        self.assertNotIn('876543',audit)
        self.assertNotIn('pin_hash',audit)
        self.assertIn('user.pin_reset',audit)

    async def test_role_change_revokes_token_and_new_manager_is_read_only(self):
        user=self.users['worker']
        response=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,role='manager'))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual((await self.client.get('/api/auth/me',headers=self.headers['worker'])).status_code,401)
        token=(await self.client.post('/api/auth/login',json={'login':user.login,'pin':'654321'})).json()['access_token']
        headers={'Authorization':'Bearer '+token}
        self.assertEqual((await self.client.get('/api/reports/shift',headers=headers)).status_code,200)
        self.assertEqual((await self.client.get('/api/admin/users',headers=headers)).status_code,403)
        self.assertEqual((await self.client.post('/api/work-orders',headers=headers,json={'description':'Test order','work_type':'planned','site_id':1,'equipment_id':1,'assignee_id':2,'priority':'normal','due_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()})).status_code,403)

    async def test_self_block_and_self_demotion_are_rejected(self):
        user=self.users['admin']
        for changes in [{'is_active':False},{'role':'manager'}]:
            response=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,**changes))
            self.assertEqual(response.status_code,409)
        self.assertEqual((await self.client.get('/api/auth/me',headers=self.headers['admin'])).status_code,200)

    async def test_stale_access_update_cannot_unblock_or_change_role(self):
        user=self.users['worker']
        response=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,is_active=False))
        self.assertEqual(response.status_code,200)
        stale=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,role='manager'))
        self.assertEqual(stale.status_code,409)
        reset=await self.client.post(f'/api/admin/users/{user.id}/reset-pin',headers=self.headers['admin'],json={'pin':'876543','expected_session_version':0})
        self.assertEqual(reset.status_code,409)

    async def test_open_orders_prevent_role_change_and_blocked_assignment(self):
        user=self.users['worker']
        async with self.sessions() as session:
            order=WorkOrder(number='ADMIN-'+uuid4().hex[:12],description='Test active order',master_id=self.users['master'].id,assignee_id=user.id,site_id=1,equipment_id=1,work_type=WorkOrderType.PLANNED,priority=WorkOrderPriority.NORMAL,status=WorkOrderStatus.ISSUED,due_at=datetime.now(UTC)+timedelta(hours=2))
            session.add(order)
            await session.commit()
        response=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,role='manager'))
        self.assertEqual(response.status_code,409)
        blocked=await self.client.put(f'/api/admin/users/{user.id}',headers=self.headers['admin'],json=self.body(user,is_active=False))
        self.assertEqual(blocked.status_code,200)
        response=await self.client.post('/api/work-orders',headers=self.headers['master'],json={'description':'New test order','work_type':'planned','site_id':1,'equipment_id':1,'assignee_id':user.id,'priority':'normal','due_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat()})
        self.assertEqual(response.status_code,422)
        async with self.sessions() as session:
            self.assertIsNotNone(await session.get(WorkOrder,order.id))

    async def test_concurrent_stale_updates_only_one_commits(self):
        user=self.users['worker']
        path=f'/api/admin/users/{user.id}'
        results=await asyncio.gather(*[self.client.put(path,headers=self.headers['admin'],json=self.body(user,is_active=False)) for _ in range(2)])
        self.assertEqual(sorted(response.status_code for response in results),[200,409])

    async def test_bootstrap_refuses_existing_admin_and_does_not_overwrite(self):
        payload=UserCreate(login='first_admin',full_name='Admin bootstrap',role='admin',pin='123456')
        with patch.object(bootstrap_admin,'SessionLocal',self.sessions):
            with self.assertRaisesRegex(ValueError,'уже есть'):
                await bootstrap_admin.bootstrap(payload)

    async def test_pagination_is_bounded(self):
        for path in ['/api/admin/users?limit=201','/api/admin/audit?offset=-1']:
            self.assertEqual((await self.client.get(path,headers=self.headers['admin'])).status_code,422)
        response=await self.client.get('/api/admin/users?limit=2',headers=self.headers['admin'])
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()),2)

    async def test_websocket_rejects_revoked_session_at_handshake(self):
        token=self.headers['worker']['Authorization'].removeprefix('Bearer ')
        client=TestClient(app)
        with patch.object(main_module,'SessionLocal',self.sessions):
            with client.websocket_connect('/api/ws?token='+token):
                pass
            response=await self.client.put(f"/api/admin/users/{self.users['worker'].id}",headers=self.headers['admin'],json=self.body(self.users['worker'],is_active=False))
            self.assertEqual(response.status_code,200)
            with self.assertRaises(WebSocketDisconnect) as failure:
                with client.websocket_connect('/api/ws?token='+token):
                    pass
            self.assertEqual(failure.exception.code,4401)
