from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import UserRole, WorkOrderPriority, WorkOrderStatus
from app.models import AiInspection, User, WorkOrder, WorkOrderCompletion, WorkOrderEvent

QOSTANAY = ZoneInfo("Asia/Qostanay")
PRIORITY_POINTS = {
    WorkOrderPriority.PLANNED: 1,
    WorkOrderPriority.NORMAL: 2,
    WorkOrderPriority.HIGH: 3,
    WorkOrderPriority.EMERGENCY: 4,
}


def default_period() -> tuple[datetime, datetime]:
    local_now = datetime.now(QOSTANAY)
    start = datetime.combine(local_now.date(), time.min, tzinfo=QOSTANAY)
    end = datetime.combine(local_now.date(), time.max, tzinfo=QOSTANAY)
    return start.astimezone(UTC), end.astimezone(UTC)


async def shift_report(session: AsyncSession, start: datetime, end: datetime) -> dict:
    orders = list((await session.scalars(select(WorkOrder).where(WorkOrder.created_at >= start, WorkOrder.created_at <= end))).all())
    order_ids = [order.id for order in orders]
    events = list((await session.scalars(select(WorkOrderEvent).where(WorkOrderEvent.work_order_id.in_(order_ids)))).all()) if order_ids else []
    now = datetime.now(UTC)
    accepted_at = {event.work_order_id: event.created_at for event in events if event.to_status == WorkOrderStatus.ACCEPTED}
    response_minutes = [max(0, (accepted_at[order.id] - order.created_at).total_seconds() / 60) for order in orders if order.id in accepted_at]
    terminal = {WorkOrderStatus.COMPLETED, WorkOrderStatus.AI_REVIEW, WorkOrderStatus.CLOSED}
    return {
        "period": {"from": start, "to": end},
        "issued": len(orders),
        "completed": sum(order.status in terminal for order in orders),
        "closed": sum(order.status == WorkOrderStatus.CLOSED for order in orders),
        "active": sum(order.status in {WorkOrderStatus.ACCEPTED, WorkOrderStatus.QUEUED, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.PAUSED, WorkOrderStatus.REWORK} for order in orders),
        "overdue": sum(order.due_at < now and order.status not in terminal for order in orders),
        "rejected": sum(event.to_status == WorkOrderStatus.REJECTED for event in events),
        "average_response_minutes": round(sum(response_minutes) / len(response_minutes), 1) if response_minutes else None,
        "by_status": {status.value: sum(order.status == status for order in orders) for status in WorkOrderStatus},
        "by_priority": {priority.value: sum(order.priority == priority for order in orders) for priority in WorkOrderPriority},
    }


async def worker_ratings(session: AsyncSession, start: datetime, end: datetime) -> list[dict]:
    workers = list((await session.scalars(select(User).where(User.role == UserRole.WORKER).order_by(User.full_name))).all())
    orders = list((await session.scalars(select(WorkOrder).where(WorkOrder.created_at >= start, WorkOrder.created_at <= end))).all())
    order_ids = [order.id for order in orders]
    completions = list((await session.scalars(select(WorkOrderCompletion).where(WorkOrderCompletion.work_order_id.in_(order_ids)))).all()) if order_ids else []
    inspections = list((await session.scalars(select(AiInspection).where(AiInspection.work_order_id.in_(order_ids)))).all()) if order_ids else []
    events = list((await session.scalars(select(WorkOrderEvent).where(WorkOrderEvent.work_order_id.in_(order_ids)))).all()) if order_ids else []
    completion_by_order = {item.work_order_id: item for item in completions}
    inspection_by_order = {item.work_order_id: item for item in inspections}
    result = []
    for worker in workers:
        assigned = [order for order in orders if order.assignee_id == worker.id]
        evaluated = [inspection_by_order[order.id] for order in assigned if order.id in inspection_by_order]
        finished = [order for order in assigned if order.id in completion_by_order]
        on_time = [order for order in finished if completion_by_order[order.id].created_at <= order.due_at]
        reworks = sum(event.to_status == WorkOrderStatus.REWORK for event in events if event.work_order_id in {order.id for order in assigned})
        rejections = sum(event.to_status == WorkOrderStatus.REJECTED for event in events if event.work_order_id in {order.id for order in assigned})
        quality = round(sum(item.score for item in evaluated) / len(evaluated), 1) if evaluated else 0
        timeliness = round(len(on_time) / len(finished) * 100, 1) if finished else 0
        reliability = max(0, round(100 - reworks / len(finished) * 100, 1)) if finished else 0
        complexity_points = sum(PRIORITY_POINTS[order.priority] for order in finished)
        productivity = min(100, round(complexity_points / 10 * 100, 1))
        discipline = max(0, 100 - rejections * 20) if assigned else 0
        total = round(quality * .35 + timeliness * .25 + reliability * .15 + productivity * .15 + discipline * .10, 1) if assigned else 0
        result.append({
            "worker_id": worker.id, "full_name": worker.full_name, "specialty": worker.specialty,
            "assigned": len(assigned), "completed": len(finished), "score": total,
            "components": {"quality": quality, "timeliness": timeliness, "reliability": reliability, "productivity": productivity, "discipline": discipline},
            "facts": {"average_quality": quality, "on_time": len(on_time), "reworks": reworks, "rejections": rejections, "complexity_points": complexity_points},
        })
    return sorted(result, key=lambda item: item["score"], reverse=True)
