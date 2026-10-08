import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import AiVerdict, UserRole, WorkOrderPriority, WorkOrderStatus, WorkOrderType
from app.models import AiInspection, Equipment, MaterialUsage, Site, User, WorkOrder, WorkOrderCompletion, WorkOrderEvent
from app.auth import hash_pin

WORKER_NAMES = [
    ("Беков Данияр", "Слесарь"), ("Иванов Павел", "Электрик"),
    ("Садыков Арман", "Сварщик"), ("Пак Сергей", "Слесарь"),
    ("Нургалиев Тимур", "Электрик"), ("Кузнецов Илья", "Сварщик"),
    ("Омаров Алибек", "Слесарь"), ("Цой Виктор", "Электрик"),
    ("Петров Максим", "Слесарь"), ("Жумабаев Руслан", "Сварщик"),
    ("Смирнов Антон", "Электрик"), ("Касымов Марат", "Слесарь"),
    ("Волков Денис", "Сварщик"),
]


async def ensure_directories(session: AsyncSession) -> tuple[list[User], list[Equipment]]:
    sites = list((await session.scalars(select(Site).order_by(Site.id))).all())
    for name in ("Ремонтно-механический цех", "Склад и погрузка"):
        if not any(site.name == name for site in sites):
            site = Site(name=name); session.add(site); sites.append(site)
    workers = list((await session.scalars(select(User).where(User.role == UserRole.WORKER))).all())
    for full_name, specialty in WORKER_NAMES:
        if len(workers) >= 15: break
        if not any(worker.full_name == full_name for worker in workers):
            worker = User(login=f"worker{len(workers) + 1}", pin_hash=hash_pin("0000"), full_name=full_name, role=UserRole.WORKER, specialty=specialty, is_on_shift=True)
            session.add(worker); workers.append(worker)
    await session.flush()
    equipment = list((await session.scalars(select(Equipment).order_by(Equipment.id))).all())
    types = ("Конвейер", "Насос", "Грохот", "Дробилка", "Редуктор", "Вентилятор")
    while len(equipment) < 25:
        index = len(equipment) + 1
        item = Equipment(name=f"{types[index % len(types)]} ДЕМО-{index:02d}", inventory_number=f"DM-{index:03d}", site_id=sites[index % len(sites)].id, criticality=1 + index % 3)
        session.add(item); equipment.append(item)
    await session.flush()
    return workers, equipment


async def generate_demo_history(session: AsyncSession, count: int = 500) -> dict:
    existing = await session.scalar(select(func.count(WorkOrder.id)).where(WorkOrder.number.like("Д-%")))
    if existing:
        return {"created": 0, "existing": existing, "message": "Демо-история уже создана"}
    rng = random.Random(20261004)
    workers, equipment = await ensure_directories(session)
    start = datetime.now(UTC) - timedelta(days=90)
    orders: list[WorkOrder] = []
    metadata: list[tuple[int, int, datetime, datetime, bool, int]] = []
    priorities = [WorkOrderPriority.NORMAL, WorkOrderPriority.NORMAL, WorkOrderPriority.HIGH, WorkOrderPriority.PLANNED, WorkOrderPriority.EMERGENCY]
    for index in range(count):
        # Конвейер К-3 намеренно получает около трети всех отказов.
        item = equipment[1] if rng.random() < .34 else rng.choice(equipment)
        worker = workers[0] if index % 9 == 0 else rng.choice(workers)
        created = start + timedelta(minutes=index * (90 * 24 * 60 / count))
        duration_hours = rng.uniform(.5, 7)
        late = index % 11 == 0
        due = created + timedelta(hours=duration_hours - .2 if late else duration_hours + 1)
        completed = created + timedelta(hours=duration_hours)
        fault_id = 2 if item.id == equipment[1].id and rng.random() < .72 else rng.randint(1, 5)
        work_type = WorkOrderType.UNPLANNED if rng.random() < .82 else WorkOrderType.PLANNED
        order = WorkOrder(number=f"Д-{index + 1:05d}", work_type=work_type, description=f"Неисправность оборудования: код {fault_id}, требуется диагностика и ремонт", site_id=item.site_id, equipment_id=item.id, assignee_id=worker.id, master_id=1, priority=rng.choice(priorities), status=WorkOrderStatus.CLOSED, due_at=due, created_at=created, updated_at=completed)
        orders.append(order)
        metadata.append((worker.id, fault_id, created, completed, late, index))
    session.add_all(orders)
    await session.flush()

    completions: list[WorkOrderCompletion] = []
    for order, (worker_id, fault_id, _, completed, _, _) in zip(orders, metadata):
        completion = WorkOrderCompletion(work_order_id=order.id, fault_code_id=fault_id, work_performed=f"Проведена диагностика, устранена неисправность по коду {fault_id}, выполнена контрольная проверка", completed_by=worker_id, created_at=completed)
        completions.append(completion)
    session.add_all(completions)
    await session.flush()

    events: list[WorkOrderEvent] = []
    inspections: list[AiInspection] = []
    usages: list[MaterialUsage] = []
    for order, completion, (worker_id, _, created, completed, late, index) in zip(orders, completions, metadata):
        accepted = created + timedelta(minutes=3 + index % 18)
        started = accepted + timedelta(minutes=2 + index % 8)
        needs_rework = worker_id == workers[0].id and index % 3 == 0
        score = max(45, 92 - (22 if needs_rework else 0) - (10 if late else 0) + rng.randint(-5, 5))
        events.extend([
            WorkOrderEvent(work_order_id=order.id, actor_id=1, from_status=None, to_status=WorkOrderStatus.ISSUED, comment="Синтетическая история", created_at=created),
            WorkOrderEvent(work_order_id=order.id, actor_id=worker_id, from_status=WorkOrderStatus.ISSUED, to_status=WorkOrderStatus.ACCEPTED, created_at=accepted),
            WorkOrderEvent(work_order_id=order.id, actor_id=worker_id, from_status=WorkOrderStatus.ACCEPTED, to_status=WorkOrderStatus.IN_PROGRESS, created_at=started),
            WorkOrderEvent(work_order_id=order.id, actor_id=worker_id, from_status=WorkOrderStatus.IN_PROGRESS, to_status=WorkOrderStatus.COMPLETED, created_at=completed),
            WorkOrderEvent(work_order_id=order.id, actor_id=1, from_status=WorkOrderStatus.COMPLETED, to_status=WorkOrderStatus.AI_REVIEW, created_at=completed + timedelta(minutes=1)),
        ])
        if needs_rework:
            events.extend([
                WorkOrderEvent(work_order_id=order.id, actor_id=1, from_status=WorkOrderStatus.AI_REVIEW, to_status=WorkOrderStatus.REWORK, comment="Заложенная закономерность", created_at=completed + timedelta(minutes=2)),
                WorkOrderEvent(work_order_id=order.id, actor_id=worker_id, from_status=WorkOrderStatus.REWORK, to_status=WorkOrderStatus.IN_PROGRESS, created_at=completed + timedelta(minutes=10)),
            ])
        events.append(WorkOrderEvent(work_order_id=order.id, actor_id=1, from_status=WorkOrderStatus.AI_REVIEW if not needs_rework else WorkOrderStatus.IN_PROGRESS, to_status=WorkOrderStatus.CLOSED, created_at=completed + timedelta(minutes=20)))
        verdict = AiVerdict.REWORK if needs_rework else (AiVerdict.ACCEPTED_WITH_COMMENTS if late else AiVerdict.ACCEPTED)
        inspections.append(AiInspection(work_order_id=order.id, completion_id=completion.id, verdict=verdict, score=score, confidence=Decimal("0.880"), checks=[], explanation="Синтетическая оценка для демонстрации аналитики", created_at=completed + timedelta(minutes=1)))
        material_id = 2 if completion.fault_code_id == 2 else rng.randint(1, 5)
        quantity = Decimal("150") if index % 97 == 0 else Decimal(str(round(rng.uniform(.5, 6), 2)))
        usages.append(MaterialUsage(completion_id=completion.id, material_id=material_id, quantity=quantity))
    session.add_all(events + inspections + usages)
    await session.commit()
    return {"created": count, "workers": len(workers), "equipment": len(equipment), "days": 90}
