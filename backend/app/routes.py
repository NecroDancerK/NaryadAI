from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domain import UserRole, WorkOrderStatus, can_transition
from app.models import Equipment, Site, User, WorkOrder, WorkOrderEvent
from app.schemas import WorkOrderCreate, WorkOrderEventRead, WorkOrderRead, WorkOrderTransition
from app.realtime import manager

router = APIRouter(prefix="/api")


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


@router.get("/directories", tags=["directories"])
async def directories(session: AsyncSession = Depends(get_session)):
    users = (await session.scalars(select(User).order_by(User.id))).all()
    equipment = (await session.scalars(select(Equipment).order_by(Equipment.id))).all()
    sites = (await session.scalars(select(Site).order_by(Site.id))).all()
    return {
        "users": [{"id": u.id, "full_name": u.full_name, "role": u.role, "specialty": u.specialty} for u in users],
        "sites": [{"id": s.id, "name": s.name} for s in sites],
        "equipment": [{"id": e.id, "name": e.name, "site_id": e.site_id, "inventory_number": e.inventory_number} for e in equipment],
    }
