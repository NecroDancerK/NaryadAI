import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domain import UserRole, WorkOrderStatus, can_transition
from app.inspection import inspect_order
from app.analytics import default_period, shift_report, worker_ratings
from app.demo_data import generate_demo_history
from app.history_analytics import analyze_history
from app.deadlines import check_deadlines
from app.models import AiInspection, Equipment, FaultCode, Material, MaterialUsage, Notification, Site, User, WorkOrder, WorkOrderCompletion, WorkOrderEvent, WorkOrderPhoto
from app.schemas import AiInspectionRead, NotificationRead, WorkOrderCreate, WorkOrderEventRead, WorkOrderRead, WorkOrderTransition
from app.realtime import manager

router = APIRouter(prefix="/api")
STORAGE_DIR = Path("storage/completions")


@router.get("/work-orders", response_model=list[WorkOrderRead], tags=["work orders"])
async def list_work_orders(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(WorkOrder).order_by(WorkOrder.created_at.desc()))).all()


@router.post("/work-orders", response_model=WorkOrderRead, status_code=status.HTTP_201_CREATED, tags=["work orders"])
async def create_work_order(payload: WorkOrderCreate, session: AsyncSession = Depends(get_session)):
    if payload.due_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Срок исполнения должен быть в будущем")
    master = await session.get(User, payload.master_id)
    assignee = await session.get(User, payload.assignee_id)
    if not master or master.role != UserRole.MASTER:
        raise HTTPException(status_code=422, detail="Мастер не найден")
    if not assignee or assignee.role != UserRole.WORKER:
        raise HTTPException(status_code=422, detail="Исполнитель не найден")
    equipment = await session.get(Equipment, payload.equipment_id)
    if not equipment or equipment.site_id != payload.site_id:
        raise HTTPException(status_code=422, detail="Оборудование не относится к выбранному участку")

    next_id = (await session.scalar(select(func.coalesce(func.max(WorkOrder.id), 0))) or 0) + 1
    order = WorkOrder(number=f"Н-{next_id:05d}", status=WorkOrderStatus.ISSUED, **payload.model_dump())
    session.add(order)
    await session.flush()
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=payload.master_id, from_status=None, to_status=WorkOrderStatus.ISSUED, comment="Наряд выдан"))
    await session.commit()
    await session.refresh(order)
    await manager.broadcast({"type": "work_order.created", "work_order_id": order.id})
    return order


@router.post("/work-orders/{order_id}/transitions", response_model=WorkOrderRead, tags=["work orders"])
async def transition_work_order(order_id: int, payload: WorkOrderTransition, session: AsyncSession = Depends(get_session)):
    order = await session.scalar(select(WorkOrder).where(WorkOrder.id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Наряд не найден")
    if not await session.get(User, payload.actor_id):
        raise HTTPException(status_code=422, detail="Пользователь не найден")
    if not can_transition(order.status, payload.status):
        raise HTTPException(status_code=409, detail=f"Переход {order.status.value} → {payload.status.value} запрещён")
    if payload.status in {WorkOrderStatus.REJECTED, WorkOrderStatus.PAUSED} and not payload.comment:
        raise HTTPException(status_code=422, detail="Для отклонения или приостановки требуется причина")
    previous = order.status
    order.status = payload.status
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=payload.actor_id, from_status=previous, to_status=payload.status, comment=payload.comment))
    await session.commit()
    await session.refresh(order)
    await manager.broadcast({"type": "work_order.status_changed", "work_order_id": order.id, "status": order.status.value})
    return order


@router.get("/work-orders/{order_id}/events", response_model=list[WorkOrderEventRead], tags=["work orders"])
async def list_events(order_id: int, session: AsyncSession = Depends(get_session)):
    if not await session.get(WorkOrder, order_id):
        raise HTTPException(status_code=404, detail="Наряд не найден")
    query = select(WorkOrderEvent).where(WorkOrderEvent.work_order_id == order_id).order_by(WorkOrderEvent.created_at, WorkOrderEvent.id)
    return (await session.scalars(query)).all()


@router.post("/work-orders/{order_id}/ai-review", response_model=AiInspectionRead, tags=["AI inspection"])
async def run_ai_review(order_id: int, session: AsyncSession = Depends(get_session)):
    order = await session.scalar(select(WorkOrder).where(WorkOrder.id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Наряд не найден")
    existing = await session.scalar(select(AiInspection).where(AiInspection.work_order_id == order_id))
    if existing:
        return existing
    if order.status != WorkOrderStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Проверить можно только исполненный наряд")
    completion = await session.scalar(select(WorkOrderCompletion).where(WorkOrderCompletion.work_order_id == order_id))
    if not completion:
        raise HTTPException(status_code=409, detail="Данные закрытия отсутствуют")
    usages = list((await session.scalars(select(MaterialUsage).where(MaterialUsage.completion_id == completion.id))).all())
    photo_count = await session.scalar(select(func.count(WorkOrderPhoto.id)).where(WorkOrderPhoto.work_order_id == order_id, WorkOrderPhoto.photo_type == "after")) or 0
    verdict, score, confidence, checks, explanation = inspect_order(order, completion, usages, photo_count)
    inspection = AiInspection(work_order_id=order.id, verdict=verdict, score=score, confidence=confidence, checks=checks, explanation=explanation)
    session.add(inspection)
    order.status = WorkOrderStatus.AI_REVIEW
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=order.master_id, from_status=WorkOrderStatus.COMPLETED, to_status=WorkOrderStatus.AI_REVIEW, comment=f"Автоматическая проверка: {verdict}, {score}/100"))
    await session.commit()
    await session.refresh(inspection)
    await manager.broadcast({"type": "work_order.ai_reviewed", "work_order_id": order.id, "status": order.status.value, "verdict": verdict})
    return inspection


@router.get("/work-orders/{order_id}/ai-review", response_model=AiInspectionRead | None, tags=["AI inspection"])
async def get_ai_review(order_id: int, session: AsyncSession = Depends(get_session)):
    return await session.scalar(select(AiInspection).where(AiInspection.work_order_id == order_id))


@router.get("/ai-reviews", response_model=list[AiInspectionRead], tags=["AI inspection"])
async def list_ai_reviews(session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(AiInspection).order_by(AiInspection.created_at.desc()))).all()


@router.get("/notifications", response_model=list[NotificationRead], tags=["notifications"])
async def list_notifications(recipient_id: int, session: AsyncSession = Depends(get_session)):
    query = select(Notification).where(Notification.recipient_id == recipient_id).order_by(Notification.created_at.desc()).limit(50)
    return (await session.scalars(query)).all()


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead, tags=["notifications"])
async def read_notification(notification_id: int, session: AsyncSession = Depends(get_session)):
    notification = await session.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    notification.is_read = True
    await session.commit()
    await session.refresh(notification)
    return notification


@router.post("/system/check-deadlines", tags=["system"])
async def run_deadline_check():
    created = await check_deadlines()
    return {"created": len(created), "notification_ids": [item.id for item in created]}


def report_period(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    default_from, default_to = default_period()
    start, end = date_from or default_from, date_to or default_to
    if start.tzinfo is None: start = start.replace(tzinfo=UTC)
    if end.tzinfo is None: end = end.replace(tzinfo=UTC)
    if start > end:
        raise HTTPException(status_code=422, detail="Начало периода позже окончания")
    return start, end


@router.get("/reports/shift", tags=["reports"])
async def get_shift_report(date_from: datetime | None = None, date_to: datetime | None = None, session: AsyncSession = Depends(get_session)):
    start, end = report_period(date_from, date_to)
    return await shift_report(session, start, end)


@router.get("/reports/ratings", tags=["reports"])
async def get_worker_ratings(date_from: datetime | None = None, date_to: datetime | None = None, session: AsyncSession = Depends(get_session)):
    start, end = report_period(date_from, date_to)
    return {"period": {"from": start, "to": end}, "weights": {"quality": 35, "timeliness": 25, "reliability": 15, "productivity": 15, "discipline": 10}, "workers": await worker_ratings(session, start, end)}


@router.post("/system/seed-demo-history", tags=["system"])
async def seed_demo_history(session: AsyncSession = Depends(get_session)):
    return await generate_demo_history(session)


@router.get("/analytics/history", tags=["analytics"])
async def history_analysis(days: int = 90, session: AsyncSession = Depends(get_session)):
    if not 7 <= days <= 365:
        raise HTTPException(status_code=422, detail="Период должен быть от 7 до 365 дней")
    return await analyze_history(session, days)


@router.post("/work-orders/{order_id}/complete", response_model=WorkOrderRead, tags=["work orders"])
async def complete_work_order(
    order_id: int,
    actor_id: int = Form(...),
    work_performed: str = Form(..., min_length=5, max_length=4000),
    fault_code_id: int = Form(...),
    materials_json: str = Form("[]"),
    comment: str | None = Form(None, max_length=2000),
    photo: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
):
    order = await session.scalar(select(WorkOrder).where(WorkOrder.id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Наряд не найден")
    if order.status != WorkOrderStatus.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Закрыть можно только наряд в работе")
    if actor_id != order.assignee_id:
        raise HTTPException(status_code=403, detail="Закрыть наряд может только назначенный исполнитель")
    if not await session.get(FaultCode, fault_code_id):
        raise HTTPException(status_code=422, detail="Шифр неисправности не найден")
    if order.work_type.value == "unplanned" and photo is None:
        raise HTTPException(status_code=422, detail="Для внеплановой работы обязательно фото после ремонта")

    try:
        raw_materials = json.loads(materials_json)
        if not isinstance(raw_materials, list):
            raise ValueError
        usages = [(int(item["material_id"]), Decimal(str(item["quantity"]))) for item in raw_materials]
    except (ValueError, TypeError, KeyError, InvalidOperation, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Некорректный список материалов")
    if any(quantity <= 0 for _, quantity in usages):
        raise HTTPException(status_code=422, detail="Количество материала должно быть больше нуля")
    material_ids = {material_id for material_id, _ in usages}
    if material_ids:
        existing = set((await session.scalars(select(Material.id).where(Material.id.in_(material_ids)))).all())
        if existing != material_ids:
            raise HTTPException(status_code=422, detail="Материал не найден")

    photo_data: bytes | None = None
    photo_path: Path | None = None
    if photo:
        if not photo.content_type or not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=422, detail="Допускаются только изображения")
        photo_data = await photo.read(10 * 1024 * 1024 + 1)
        if len(photo_data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Фото превышает 10 МБ")

    completion = WorkOrderCompletion(work_order_id=order.id, fault_code_id=fault_code_id, work_performed=work_performed, comment=comment, completed_by=actor_id)
    session.add(completion)
    await session.flush()
    for material_id, quantity in usages:
        session.add(MaterialUsage(completion_id=completion.id, material_id=material_id, quantity=quantity))
    if photo and photo_data is not None:
        suffix = Path(photo.filename or "photo.jpg").suffix.lower()[:10] or ".jpg"
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        photo_path = STORAGE_DIR / f"{order.id}-{uuid4().hex}{suffix}"
        photo_path.write_bytes(photo_data)
        session.add(WorkOrderPhoto(work_order_id=order.id, photo_type="after", file_path=str(photo_path), original_name=photo.filename, content_type=photo.content_type, uploaded_by=actor_id))
    order.status = WorkOrderStatus.COMPLETED
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=actor_id, from_status=WorkOrderStatus.IN_PROGRESS, to_status=WorkOrderStatus.COMPLETED, comment="Исполнитель отправил наряд на проверку"))
    try:
        await session.commit()
    except Exception:
        if photo_path:
            photo_path.unlink(missing_ok=True)
        raise
    await session.refresh(order)
    await manager.broadcast({"type": "work_order.completed", "work_order_id": order.id, "status": order.status.value})
    return order


@router.get("/directories", tags=["directories"])
async def directories(session: AsyncSession = Depends(get_session)):
    users = (await session.scalars(select(User).order_by(User.id))).all()
    equipment = (await session.scalars(select(Equipment).order_by(Equipment.id))).all()
    sites = (await session.scalars(select(Site).order_by(Site.id))).all()
    fault_codes = (await session.scalars(select(FaultCode).order_by(FaultCode.code))).all()
    materials = (await session.scalars(select(Material).order_by(Material.name))).all()
    return {
        "users": [{"id": u.id, "full_name": u.full_name, "role": u.role, "specialty": u.specialty} for u in users],
        "sites": [{"id": s.id, "name": s.name} for s in sites],
        "equipment": [{"id": e.id, "name": e.name, "site_id": e.site_id, "inventory_number": e.inventory_number} for e in equipment],
        "fault_codes": [{"id": f.id, "code": f.code, "name": f.name} for f in fault_codes],
        "materials": [{"id": m.id, "name": m.name, "unit": m.unit} for m in materials],
    }
