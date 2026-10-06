import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domain import UserRole, WorkOrderStatus, can_transition
from app.auth import create_access_token, current_user, require_roles, verify_pin
from app.inspection import inspect_order
from app.analytics import default_period, shift_report, worker_ratings
from app.demo_data import generate_demo_history
from app.history_analytics import analyze_history
from app.llm import llm_status, semantic_review
from app.deadlines import check_deadlines
from app.models import AiInspection, Equipment, FaultCode, Material, MaterialUsage, Notification, Site, User, WorkOrder, WorkOrderCompletion, WorkOrderEvent, WorkOrderPhoto
from app.schemas import AuthLogin, AuthToken, AiInspectionRead, CurrentUserRead, NotificationRead, WorkOrderCreate, WorkOrderEventRead, WorkOrderRead, WorkOrderTransition
from app.realtime import manager

router = APIRouter(prefix="/api")
STORAGE_DIR = Path("storage/completions")


async def accessible_order(order_id: int, user: User, session: AsyncSession, for_update: bool = False) -> WorkOrder:
    query = select(WorkOrder).where(WorkOrder.id == order_id)
    if for_update:
        query = query.with_for_update()
    order = await session.scalar(query)
    if not order:
        raise HTTPException(status_code=404, detail="Наряд не найден")
    if user.role == UserRole.WORKER and order.assignee_id != user.id:
        raise HTTPException(status_code=403, detail="Этот наряд назначен другому исполнителю")
    if user.role == UserRole.MASTER and order.master_id != user.id:
        raise HTTPException(status_code=403, detail="Этот наряд выдан другим мастером")
    return order


@router.post("/auth/login", response_model=AuthToken, tags=["auth"])
async def login(payload: AuthLogin, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(func.lower(User.login) == payload.login.strip().lower()))
    if not user or not verify_pin(payload.pin, user.pin_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или PIN-код")
    return AuthToken(access_token=create_access_token(user), user=CurrentUserRead.model_validate(user))


@router.get("/auth/me", response_model=CurrentUserRead, tags=["auth"])
async def me(user: User = Depends(current_user)):
    return user


@router.get("/work-orders", response_model=list[WorkOrderRead], tags=["work orders"])
async def list_work_orders(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    recent_cutoff = datetime.now(UTC) - timedelta(hours=24)
    query = select(WorkOrder).where(
        (WorkOrder.status != WorkOrderStatus.CLOSED) | (WorkOrder.updated_at >= recent_cutoff)
    )
    if user.role == UserRole.WORKER:
        query = query.where(WorkOrder.assignee_id == user.id)
    elif user.role == UserRole.MASTER:
        query = query.where(WorkOrder.master_id == user.id)
    return (await session.scalars(query.order_by(WorkOrder.created_at.desc()).limit(200))).all()


async def persist_work_order(payload: WorkOrderCreate, master: User, session: AsyncSession, photos: list[tuple[UploadFile, bytes]] | None = None) -> WorkOrder:
    if payload.due_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Срок исполнения должен быть в будущем")
    assignee = await session.get(User, payload.assignee_id)
    if not assignee or assignee.role != UserRole.WORKER:
        raise HTTPException(status_code=422, detail="Исполнитель не найден")
    equipment = await session.get(Equipment, payload.equipment_id)
    if not equipment or equipment.site_id != payload.site_id:
        raise HTTPException(status_code=422, detail="Оборудование не относится к выбранному участку")

    next_id = (await session.scalar(select(func.coalesce(func.max(WorkOrder.id), 0))) or 0) + 1
    order = WorkOrder(number=f"Н-{next_id:05d}", status=WorkOrderStatus.ISSUED, master_id=master.id, **payload.model_dump())
    session.add(order)
    await session.flush()
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=master.id, from_status=None, to_status=WorkOrderStatus.ISSUED, comment="Наряд выдан"))
    saved_paths: list[Path] = []
    try:
        for photo, data in photos or []:
            suffix = Path(photo.filename or "photo.jpg").suffix.lower()[:10] or ".jpg"
            STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            photo_path = STORAGE_DIR / f"{order.id}-{uuid4().hex}{suffix}"
            photo_path.write_bytes(data)
            saved_paths.append(photo_path)
            session.add(WorkOrderPhoto(work_order_id=order.id, photo_type="before", file_path=str(photo_path), original_name=photo.filename, content_type=photo.content_type or "application/octet-stream", uploaded_by=master.id))
        await session.commit()
    except Exception:
        await session.rollback()
        for photo_path in saved_paths:
            photo_path.unlink(missing_ok=True)
        raise
    await session.refresh(order)
    await manager.broadcast({"type": "work_order.created", "work_order_id": order.id})
    return order


@router.post("/work-orders", response_model=WorkOrderRead, status_code=status.HTTP_201_CREATED, tags=["work orders"])
async def create_work_order(payload: WorkOrderCreate, master: User = Depends(require_roles(UserRole.MASTER, UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    return await persist_work_order(payload, master, session)


@router.post("/work-orders/with-photos", response_model=WorkOrderRead, status_code=status.HTTP_201_CREATED, tags=["work orders"])
async def create_work_order_with_photos(
    payload: str = Form(...),
    photos: list[UploadFile] = File(default=[]),
    master: User = Depends(require_roles(UserRole.MASTER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
):
    try:
        work_order = WorkOrderCreate.model_validate_json(payload)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    if len(photos) > 5:
        raise HTTPException(status_code=422, detail="Можно приложить не более 5 фотографий")

    photo_data: list[tuple[UploadFile, bytes]] = []
    for photo in photos:
        if not photo.content_type or not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=422, detail="Допускаются только изображения")
        data = await photo.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Фото превышает 10 МБ")
        photo_data.append((photo, data))

    return await persist_work_order(work_order, master, session, photo_data)


@router.post("/work-orders/{order_id}/transitions", response_model=WorkOrderRead, tags=["work orders"])
async def transition_work_order(order_id: int, payload: WorkOrderTransition, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    order = await accessible_order(order_id, user, session, for_update=True)
    worker_targets = {WorkOrderStatus.ACCEPTED, WorkOrderStatus.QUEUED, WorkOrderStatus.REJECTED, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.PAUSED}
    master_targets = {WorkOrderStatus.ISSUED, WorkOrderStatus.REWORK, WorkOrderStatus.CLOSED}
    if user.role == UserRole.WORKER and payload.status not in worker_targets:
        raise HTTPException(status_code=403, detail="Переход недоступен исполнителю")
    if user.role == UserRole.MASTER and payload.status not in master_targets:
        raise HTTPException(status_code=403, detail="Переход недоступен мастеру")
    if user.role == UserRole.MANAGER:
        raise HTTPException(status_code=403, detail="Руководителю доступен только просмотр")
    if not can_transition(order.status, payload.status):
        raise HTTPException(status_code=409, detail=f"Переход {order.status.value} → {payload.status.value} запрещён")
    if payload.status in {WorkOrderStatus.REJECTED, WorkOrderStatus.PAUSED} and not payload.comment:
        raise HTTPException(status_code=422, detail="Для отклонения или приостановки требуется причина")
    previous = order.status
    order.status = payload.status
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=user.id, from_status=previous, to_status=payload.status, comment=payload.comment))
    await session.commit()
    await session.refresh(order)
    await manager.broadcast({"type": "work_order.status_changed", "work_order_id": order.id, "status": order.status.value})
    return order


@router.get("/work-orders/{order_id}/events", response_model=list[WorkOrderEventRead], tags=["work orders"])
async def list_events(order_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await accessible_order(order_id, user, session)
    query = select(WorkOrderEvent).where(WorkOrderEvent.work_order_id == order_id).order_by(WorkOrderEvent.created_at, WorkOrderEvent.id)
    return (await session.scalars(query)).all()


@router.get("/work-orders/{order_id}/photos/{photo_id}/file", tags=["work orders"])
async def get_work_order_photo(order_id: int, photo_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await accessible_order(order_id, user, session)
    photo = await session.scalar(select(WorkOrderPhoto).where(
        WorkOrderPhoto.id == photo_id,
        WorkOrderPhoto.work_order_id == order_id,
    ))
    if not photo or not Path(photo.file_path).is_file():
        raise HTTPException(status_code=404, detail="Фото не найдено")
    return FileResponse(photo.file_path, media_type=photo.content_type)


@router.get("/work-orders/{order_id}/report", tags=["work orders"])
async def get_work_order_report(order_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    order = await accessible_order(order_id, user, session)
    site = await session.get(Site, order.site_id)
    equipment = await session.get(Equipment, order.equipment_id)
    assignee = await session.get(User, order.assignee_id)
    master = await session.get(User, order.master_id)
    event_rows = (await session.execute(
        select(WorkOrderEvent, User.full_name)
        .join(User, User.id == WorkOrderEvent.actor_id)
        .where(WorkOrderEvent.work_order_id == order.id)
        .order_by(WorkOrderEvent.created_at, WorkOrderEvent.id)
    )).all()
    completion = await session.scalar(select(WorkOrderCompletion).where(WorkOrderCompletion.work_order_id == order.id))
    inspection = await session.scalar(select(AiInspection).where(AiInspection.work_order_id == order.id))
    photos = (await session.scalars(
        select(WorkOrderPhoto).where(WorkOrderPhoto.work_order_id == order.id).order_by(WorkOrderPhoto.created_at, WorkOrderPhoto.id)
    )).all()

    completion_data = None
    if completion:
        fault = await session.get(FaultCode, completion.fault_code_id)
        material_rows = (await session.execute(
            select(MaterialUsage, Material)
            .join(Material, Material.id == MaterialUsage.material_id)
            .where(MaterialUsage.completion_id == completion.id)
            .order_by(Material.name)
        )).all()
        completion_data = {
            "work_performed": completion.work_performed,
            "comment": completion.comment,
            "created_at": completion.created_at,
            "fault_code": {"code": fault.code, "name": fault.name} if fault else None,
            "materials": [{"name": material.name, "quantity": usage.quantity, "unit": material.unit} for usage, material in material_rows],
        }

    return {
        "order": {
            "id": order.id,
            "number": order.number,
            "description": order.description,
            "work_type": order.work_type.value,
            "priority": order.priority.value,
            "status": order.status.value,
            "due_at": order.due_at,
            "created_at": order.created_at,
            "site_name": site.name if site else None,
            "equipment_name": equipment.name if equipment else None,
            "inventory_number": equipment.inventory_number if equipment else None,
            "assignee_name": assignee.full_name if assignee else None,
            "master_name": master.full_name if master else None,
        },
        "events": [{
            "actor_name": actor_name,
            "from_status": event.from_status.value if event.from_status else None,
            "to_status": event.to_status.value,
            "comment": event.comment,
            "created_at": event.created_at,
        } for event, actor_name in event_rows],
        "completion": completion_data,
        "inspection": {
            "verdict": inspection.verdict.value,
            "score": inspection.score,
            "confidence": float(inspection.confidence),
            "checks": inspection.checks,
            "explanation": inspection.explanation,
            "analysis_source": inspection.analysis_source,
            "model_name": inspection.model_name,
            "created_at": inspection.created_at,
        } if inspection else None,
        "photos": [{
            "id": photo.id,
            "photo_type": photo.photo_type,
            "original_name": photo.original_name,
            "created_at": photo.created_at,
        } for photo in photos],
    }


@router.post("/work-orders/{order_id}/ai-review", response_model=AiInspectionRead, tags=["AI inspection"])
async def run_ai_review(order_id: int, master: User = Depends(require_roles(UserRole.MASTER, UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    order = await accessible_order(order_id, master, session, for_update=True)
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
    fault = await session.get(FaultCode, completion.fault_code_id)
    material_ids = {usage.material_id for usage in usages}
    material_map = {item.id: item for item in (await session.scalars(select(Material).where(Material.id.in_(material_ids)))).all()} if material_ids else {}
    material_labels = [f"{material_map[usage.material_id].name}: {usage.quantity} {material_map[usage.material_id].unit}" for usage in usages if usage.material_id in material_map]
    llm_result = await semantic_review(order.description, completion.work_performed, f"{fault.code} — {fault.name}" if fault else "не указан", material_labels)
    verdict, score, confidence, checks, explanation = inspect_order(order, completion, usages, photo_count, llm_result)
    inspection = AiInspection(work_order_id=order.id, verdict=verdict, score=score, confidence=confidence, checks=checks, explanation=explanation, analysis_source=llm_result.source, model_name=llm_result.model, llm_error=llm_result.error)
    session.add(inspection)
    order.status = WorkOrderStatus.AI_REVIEW
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=master.id, from_status=WorkOrderStatus.COMPLETED, to_status=WorkOrderStatus.AI_REVIEW, comment=f"Автоматическая проверка: {verdict}, {score}/100"))
    await session.commit()
    await session.refresh(inspection)
    await manager.broadcast({"type": "work_order.ai_reviewed", "work_order_id": order.id, "status": order.status.value, "verdict": verdict})
    return inspection


@router.get("/work-orders/{order_id}/ai-review", response_model=AiInspectionRead | None, tags=["AI inspection"])
async def get_ai_review(order_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await accessible_order(order_id, user, session)
    return await session.scalar(select(AiInspection).where(AiInspection.work_order_id == order_id))


@router.get("/ai-reviews", response_model=list[AiInspectionRead], tags=["AI inspection"])
async def list_ai_reviews(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    query = select(AiInspection).join(WorkOrder, WorkOrder.id == AiInspection.work_order_id)
    if user.role == UserRole.WORKER:
        query = query.where(WorkOrder.assignee_id == user.id)
    elif user.role == UserRole.MASTER:
        query = query.where(WorkOrder.master_id == user.id)
    return (await session.scalars(query.order_by(AiInspection.created_at.desc()))).all()


@router.get("/ai/status", tags=["AI inspection"])
async def get_llm_status(_: User = Depends(current_user)):
    return await llm_status()


@router.get("/notifications", response_model=list[NotificationRead], tags=["notifications"])
async def list_notifications(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    query = select(Notification).where(Notification.recipient_id == user.id).order_by(Notification.created_at.desc()).limit(50)
    return (await session.scalars(query)).all()


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead, tags=["notifications"])
async def read_notification(notification_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    notification = await session.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    if notification.recipient_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Уведомление принадлежит другому пользователю")
    notification.is_read = True
    await session.commit()
    await session.refresh(notification)
    return notification


@router.post("/system/check-deadlines", tags=["system"])
async def run_deadline_check(_: User = Depends(require_roles(UserRole.MASTER, UserRole.ADMIN))):
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
async def get_shift_report(date_from: datetime | None = None, date_to: datetime | None = None, _: User = Depends(require_roles(UserRole.MASTER, UserRole.MANAGER, UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    start, end = report_period(date_from, date_to)
    return await shift_report(session, start, end)


@router.get("/reports/ratings", tags=["reports"])
async def get_worker_ratings(date_from: datetime | None = None, date_to: datetime | None = None, _: User = Depends(require_roles(UserRole.MASTER, UserRole.MANAGER, UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    start, end = report_period(date_from, date_to)
    return {"period": {"from": start, "to": end}, "weights": {"quality": 35, "timeliness": 25, "reliability": 15, "productivity": 15, "discipline": 10}, "workers": await worker_ratings(session, start, end)}


@router.post("/system/seed-demo-history", tags=["system"])
async def seed_demo_history(_: User = Depends(require_roles(UserRole.MASTER, UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    return await generate_demo_history(session)


@router.get("/analytics/history", tags=["analytics"])
async def history_analysis(days: int = 90, _: User = Depends(require_roles(UserRole.MASTER, UserRole.MANAGER, UserRole.ADMIN)), session: AsyncSession = Depends(get_session)):
    if not 7 <= days <= 365:
        raise HTTPException(status_code=422, detail="Период должен быть от 7 до 365 дней")
    return await analyze_history(session, days)


@router.post("/work-orders/{order_id}/complete", response_model=WorkOrderRead, tags=["work orders"])
async def complete_work_order(
    order_id: int,
    work_performed: str = Form(..., min_length=5, max_length=4000),
    fault_code_id: int = Form(...),
    materials_json: str = Form("[]"),
    comment: str | None = Form(None, max_length=2000),
    photo: UploadFile | None = File(None),
    user: User = Depends(require_roles(UserRole.WORKER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
):
    order = await accessible_order(order_id, user, session, for_update=True)
    if order.status != WorkOrderStatus.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Закрыть можно только наряд в работе")
    if user.role != UserRole.ADMIN and user.id != order.assignee_id:
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

    completion = WorkOrderCompletion(work_order_id=order.id, fault_code_id=fault_code_id, work_performed=work_performed, comment=comment, completed_by=user.id)
    session.add(completion)
    await session.flush()
    for material_id, quantity in usages:
        session.add(MaterialUsage(completion_id=completion.id, material_id=material_id, quantity=quantity))
    if photo and photo_data is not None:
        suffix = Path(photo.filename or "photo.jpg").suffix.lower()[:10] or ".jpg"
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        photo_path = STORAGE_DIR / f"{order.id}-{uuid4().hex}{suffix}"
        photo_path.write_bytes(photo_data)
        session.add(WorkOrderPhoto(work_order_id=order.id, photo_type="after", file_path=str(photo_path), original_name=photo.filename, content_type=photo.content_type, uploaded_by=user.id))
    order.status = WorkOrderStatus.COMPLETED
    session.add(WorkOrderEvent(work_order_id=order.id, actor_id=user.id, from_status=WorkOrderStatus.IN_PROGRESS, to_status=WorkOrderStatus.COMPLETED, comment="Исполнитель отправил наряд на проверку"))
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
async def directories(_: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
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


@router.get("/shift/workers", tags=["shift"])
async def shift_workers(
    _: User = Depends(require_roles(UserRole.MASTER, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
):
    workers = list((await session.scalars(select(User).where(User.role == UserRole.WORKER).order_by(User.full_name))).all())
    if not workers:
        return []

    worker_ids = [worker.id for worker in workers]
    active_statuses = {
        WorkOrderStatus.ISSUED,
        WorkOrderStatus.ACCEPTED,
        WorkOrderStatus.QUEUED,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.PAUSED,
        WorkOrderStatus.REWORK,
    }
    orders = list((await session.scalars(
        select(WorkOrder).where(
            WorkOrder.assignee_id.in_(worker_ids),
            WorkOrder.status.in_(active_statuses),
        ).order_by(WorkOrder.created_at)
    )).all())
    orders_by_worker: dict[int, list[WorkOrder]] = {worker_id: [] for worker_id in worker_ids}
    for order in orders:
        orders_by_worker[order.assignee_id].append(order)

    result = []
    for worker in workers:
        assigned = orders_by_worker[worker.id]
        current_order = next((order for order in assigned if order.status in {
            WorkOrderStatus.ACCEPTED,
            WorkOrderStatus.IN_PROGRESS,
            WorkOrderStatus.PAUSED,
        }), None)
        waiting = [order for order in assigned if order.status in {
            WorkOrderStatus.ISSUED,
            WorkOrderStatus.QUEUED,
            WorkOrderStatus.REWORK,
        }]
        state = "off_shift" if not worker.is_on_shift else "busy" if current_order else "queued" if waiting else "free"
        result.append({
            "id": worker.id,
            "full_name": worker.full_name,
            "specialty": worker.specialty,
            "state": state,
            "current_order_number": current_order.number if current_order else None,
            "queue_count": len(waiting),
        })
    return result
