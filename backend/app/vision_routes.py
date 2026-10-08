import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_roles
from app.config import settings
from app.database import get_session
from app.domain import UserRole, WorkOrderStatus
from app.models import PhotoObservation, User, WorkOrderCompletion, WorkOrderPhoto
from app.routes import accessible_order
from app.vision import PROMPT_VERSION, VisionError, observe

router = APIRouter(prefix="/api", tags=["photo observations"])
gpu_lock = asyncio.Lock()


def observation_read(row: PhotoObservation | None):
    if row is None:
        return None
    return {key: getattr(row, key) for key in ("completion_id", "status", "model_name", "prompt_version", "photo_ids", "result", "error", "started_at", "finished_at")}


@router.post("/work-orders/{order_id}/completions/{completion_id}/vision")
async def analyze_photos(order_id: int, completion_id: int, user: User = Depends(require_roles(UserRole.MASTER, UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    order = await accessible_order(order_id, user, session, for_update=True)
    latest = await session.scalar(select(WorkOrderCompletion).where(WorkOrderCompletion.work_order_id == order.id).order_by(WorkOrderCompletion.id.desc()).limit(1))
    if not latest or latest.id != completion_id:
        raise HTTPException(409, "Анализ запускается только для последнего отчёта")
    existing = await session.scalar(select(PhotoObservation).where(PhotoObservation.completion_id == completion_id))
    now = datetime.now(UTC)
    if existing and (existing.status == "done" or (existing.status == "running" and now < existing.started_at + timedelta(seconds=settings.vlm_timeout_seconds + 30))):
        return observation_read(existing)
    if order.status not in {WorkOrderStatus.COMPLETED, WorkOrderStatus.AI_REVIEW, WorkOrderStatus.CLOSED}:
        raise HTTPException(409, "Дождитесь сдачи работ исполнителем")
    if not settings.vlm_enabled:
        raise HTTPException(503, "VLM отключена конфигурацией")
    after = await session.scalar(select(WorkOrderPhoto).where(WorkOrderPhoto.completion_id == completion_id, WorkOrderPhoto.photo_type == "after").order_by(WorkOrderPhoto.id.desc()).limit(1))
    if not after:
        raise HTTPException(422, "Для анализа нужно фото после работ")
    before = await session.scalar(select(WorkOrderPhoto).where(WorkOrderPhoto.work_order_id == order.id, WorkOrderPhoto.photo_type == "before").order_by(WorkOrderPhoto.id).limit(1))
    photos = [before, after] if before else [after]
    # Single-process MVP: no in-memory backlog that could hide lost tasks.
    if gpu_lock.locked():
        raise HTTPException(429, "VLM занята другим фотоотчётом. Повторите позже")
    async with gpu_lock:
        row = existing or PhotoObservation(completion_id=completion_id)
        attempt = str(uuid4())
        row.status, row.attempt = "running", attempt
        row.model_name, row.prompt_version = settings.vlm_model, PROMPT_VERSION
        row.photo_ids, row.started_at = [photo.id for photo in photos], now
        row.result, row.error, row.finished_at = None, None, None
        session.add(row)
        await session.commit()  # No order lock during GPU inference; human decisions remain usable.
        try:
            result, error = await observe(photos), None
        except VisionError as cause:
            result, error = None, str(cause)
        except OSError:
            result, error = None, "Не удалось прочитать сохранённое фото"
        current = await session.scalar(select(PhotoObservation).where(PhotoObservation.completion_id == completion_id).with_for_update().execution_options(populate_existing=True))
        if current.attempt == attempt:
            current.status = "done" if result is not None else "failed"
            current.result, current.error, current.finished_at = result, error, datetime.now(UTC)
            await session.commit()
        return observation_read(current)
