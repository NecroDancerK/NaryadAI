import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.domain import WorkOrderPriority, WorkOrderStatus
from app.models import Notification, WorkOrder
from app.realtime import manager

ACTIVE_STATUSES = {
    WorkOrderStatus.ISSUED,
    WorkOrderStatus.ACCEPTED,
    WorkOrderStatus.QUEUED,
    WorkOrderStatus.IN_PROGRESS,
    WorkOrderStatus.PAUSED,
    WorkOrderStatus.REWORK,
}


async def add_once(session: AsyncSession, order: WorkOrder, recipient_id: int, kind: str, title: str, message: str) -> Notification | None:
    existing = await session.scalar(select(Notification.id).where(Notification.work_order_id == order.id, Notification.recipient_id == recipient_id, Notification.kind == kind))
    if existing:
        return None
    notification = Notification(work_order_id=order.id, recipient_id=recipient_id, kind=kind, title=title, message=message)
    session.add(notification)
    return notification


async def check_deadlines() -> list[Notification]:
    now = datetime.now(UTC)
    created: list[Notification] = []
    async with SessionLocal() as session:
        orders = list((await session.scalars(select(WorkOrder).where(WorkOrder.status.in_(ACTIVE_STATUSES)))).all())
        for order in orders:
            if now < order.due_at <= now + timedelta(minutes=30):
                item = await add_once(session, order, order.assignee_id, "deadline_soon", f"Срок наряда {order.number} приближается", f"До срока исполнения осталось менее 30 минут. Статус: {order.status.value}.")
                if item: created.append(item)
            if order.due_at <= now:
                overdue_minutes = max(1, int((now - order.due_at).total_seconds() // 60))
                for recipient_id in {order.assignee_id, order.master_id}:
                    item = await add_once(session, order, recipient_id, "overdue", f"Наряд {order.number} просрочен", f"Просрочка: {overdue_minutes} мин. Статус: {order.status.value}. {order.description}")
                    if item: created.append(item)
            if order.status == WorkOrderStatus.ISSUED:
                threshold = timedelta(minutes=3 if order.priority == WorkOrderPriority.EMERGENCY else 10)
                if order.created_at + threshold <= now:
                    item = await add_once(session, order, order.master_id, "unaccepted", f"Наряд {order.number} не принят", "Назначенный исполнитель не ответил вовремя. Рекомендуется выбрать другого свободного исполнителя.")
                    if item: created.append(item)
        await session.commit()
        for item in created:
            await session.refresh(item)
    for item in created:
        await manager.broadcast({"type": "notification.created", "notification_id": item.id, "recipient_id": item.recipient_id, "kind": item.kind})
    return created


async def deadline_loop(interval_seconds: int = 15) -> None:
    while True:
        with suppress(Exception):
            await check_deadlines()
        await asyncio.sleep(interval_seconds)
