from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import WorkOrderType
from app.models import Equipment, FaultCode, Material, MaterialUsage, WorkOrder, WorkOrderCompletion


async def analyze_history(session: AsyncSession, days: int = 90) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    orders = list((await session.scalars(select(WorkOrder).where(WorkOrder.created_at >= since))).all())
    order_ids = [order.id for order in orders]
    completions = list((await session.scalars(select(WorkOrderCompletion).where(WorkOrderCompletion.work_order_id.in_(order_ids)))).all()) if order_ids else []
    completion_by_order = {item.work_order_id: item for item in completions}
    completion_ids = [item.id for item in completions]
    usages = list((await session.scalars(select(MaterialUsage).where(MaterialUsage.completion_id.in_(completion_ids)))).all()) if completion_ids else []
    equipment = {item.id: item for item in (await session.scalars(select(Equipment))).all()}
    fault_codes = {item.id: item for item in (await session.scalars(select(FaultCode))).all()}
    materials = {item.id: item for item in (await session.scalars(select(Material))).all()}

    unplanned_counts = Counter(order.equipment_id for order in orders if order.work_type == WorkOrderType.UNPLANNED)
    downtime_hours: dict[int, float] = defaultdict(float)
    fault_equipment = Counter()
    for order in orders:
        completion = completion_by_order.get(order.id)
        if completion:
            downtime_hours[order.equipment_id] += max(0, (completion.created_at - order.created_at).total_seconds() / 3600)
            if order.work_type == WorkOrderType.UNPLANNED:
                fault_equipment[(order.equipment_id, completion.fault_code_id)] += 1

    top_equipment = []
    for equipment_id, count in unplanned_counts.most_common(10):
        item = equipment[equipment_id]
        top_equipment.append({"equipment_id": equipment_id, "name": item.name, "unplanned_failures": count, "downtime_hours": round(downtime_hours[equipment_id], 1)})

    repeated_faults = []
    for (equipment_id, fault_id), count in fault_equipment.most_common():
        if count < 4: continue
        repeated_faults.append({"equipment_id": equipment_id, "equipment": equipment[equipment_id].name, "fault_code": fault_codes[fault_id].code, "fault": fault_codes[fault_id].name, "count": count, "recommendation": "Провести анализ первопричины и включить узел в ближайший план ППР."})

    values_by_material: dict[int, list[float]] = defaultdict(list)
    for usage in usages: values_by_material[usage.material_id].append(float(usage.quantity))
    anomalies = []
    completion_by_id = {item.id: item for item in completions}
    order_by_id = {item.id: item for item in orders}
    for usage in usages:
        values = values_by_material[usage.material_id]
        if len(values) < 5: continue
        avg, deviation = mean(values), pstdev(values)
        if deviation and float(usage.quantity) > avg + 3 * deviation:
            completion = completion_by_id[usage.completion_id]
            order = order_by_id[completion.work_order_id]
            anomalies.append({"work_order": order.number, "material": materials[usage.material_id].name, "quantity": float(usage.quantity), "average": round(avg, 2), "deviation_factor": round(float(usage.quantity) / max(avg, .001), 1)})

    patterns = []
    if top_equipment:
        leader = top_equipment[0]
        baseline = mean([item["unplanned_failures"] for item in top_equipment[1:]]) if len(top_equipment) > 1 else leader["unplanned_failures"]
        patterns.append({"kind": "problem_equipment", "severity": "high" if leader["unplanned_failures"] >= baseline * 2 else "medium", "title": f"{leader['name']} — лидер по внеплановым отказам", "evidence": f"{leader['unplanned_failures']} отказов и {leader['downtime_hours']} ч простоя за {days} дней; среднее остальных из топа — {baseline:.1f}.", "recommendation": "Назначить диагностику узлов с повторяющимися шифрами и скорректировать ППР."})
    if repeated_faults:
        repeated = repeated_faults[0]
        patterns.append({"kind": "repeated_fault", "severity": "high", "title": f"Повторяющийся отказ {repeated['fault_code']} на {repeated['equipment']}", "evidence": f"Один шифр зарегистрирован {repeated['count']} раз за {days} дней.", "recommendation": repeated["recommendation"]})
    if anomalies:
        patterns.append({"kind": "material_anomaly", "severity": "medium", "title": "Обнаружен аномальный расход материалов", "evidence": f"Найдено {len(anomalies)} списаний выше среднего более чем на 3 стандартных отклонения.", "recommendation": "Проверить первичные документы и нормативы расхода по отмеченным нарядам."})

    return {"period_days": days, "orders_analyzed": len(orders), "top_equipment": top_equipment, "repeated_faults": repeated_faults[:10], "material_anomalies": anomalies[:20], "patterns": patterns}
