import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.domain import WorkOrderType
from app.models import MaterialUsage, WorkOrder, WorkOrderCompletion
from app.llm import LlmResult


@dataclass
class Check:
    code: str
    label: str
    passed: bool
    severity: str
    detail: str


STOP_WORDS = {"для", "или", "при", "после", "нужно", "работы", "работ", "выполнить", "устранить", "проверить", "заменить"}


def words(value: str) -> set[str]:
    return {word for word in re.findall(r"[а-яёa-z0-9]{3,}", value.lower()) if word not in STOP_WORDS}


def inspect_order(order: WorkOrder, completion: WorkOrderCompletion, usages: list[MaterialUsage], photo_count: int, llm_result: LlmResult | None = None) -> tuple[str, int, Decimal, list[dict], str]:
    checks: list[Check] = []
    checks.append(Check("work_performed", "Описание выполненных работ", len(completion.work_performed.strip()) >= 10, "critical", "Описание заполнено" if len(completion.work_performed.strip()) >= 10 else "Описание слишком короткое"))
    checks.append(Check("fault_code", "Шифр неисправности", completion.fault_code_id > 0, "critical", "Шифр выбран"))
    photo_required = order.work_type == WorkOrderType.UNPLANNED
    photo_ok = photo_count > 0 or not photo_required
    checks.append(Check("photo_after", "Фото после ремонта", photo_ok, "critical", "Фото приложено" if photo_count else ("Фото не обязательно" if not photo_required else "Нет обязательного фото")))

    excessive = [usage for usage in usages if usage.quantity > Decimal("100")]
    checks.append(Check("materials", "Расход материалов", not excessive, "warning", "Расход выглядит допустимым" if not excessive else "Есть количество свыше демонстрационного порога 100"))
    finished_at = completion.created_at if completion.created_at.tzinfo else completion.created_at.replace(tzinfo=UTC)
    checks.append(Check("deadline", "Срок исполнения", finished_at <= order.due_at, "warning", "Выполнено в срок" if finished_at <= order.due_at else "Работа завершена после срока"))

    semantic_score: int | None = None
    if llm_result and llm_result.available and llm_result.semantic:
        semantic_ok = llm_result.semantic.match
        semantic_score = llm_result.semantic.score
        semantic_detail = llm_result.semantic.explanation
        if llm_result.semantic.issues:
            semantic_detail += " Замечания: " + "; ".join(llm_result.semantic.issues)
    else:
        problem_words = words(order.description)
        result_words = words(completion.work_performed)
        overlap = len(problem_words & result_words) / max(1, len(problem_words))
        semantic_ok = overlap >= 0.15
        semantic_detail = f"Базовое текстовое соответствие: {round(overlap * 100)}%"
    checks.append(Check("semantic_match", "Соответствие работ проблеме", semantic_ok, "warning", semantic_detail))

    critical_failures = [check for check in checks if not check.passed and check.severity == "critical"]
    warnings = [check for check in checks if not check.passed and check.severity == "warning"]
    if critical_failures:
        verdict, score = "rework", max(20, 60 - len(critical_failures) * 20)
    elif warnings:
        verdict, score = "accepted_with_comments", max(60, 90 - len(warnings) * 10)
    else:
        verdict, score = "accepted", 95
    if semantic_score is not None and not critical_failures:
        score = round(score * .6 + semantic_score * .4)
    failed_details = [check.detail for check in checks if not check.passed]
    explanation = "Все обязательные проверки пройдены." if not failed_details else "Замечания: " + "; ".join(failed_details) + "."
    if llm_result and llm_result.available and llm_result.semantic:
        confidence = Decimal(str(round(llm_result.semantic.confidence, 3)))
    else:
        confidence = Decimal("0.650") if not semantic_ok else Decimal("0.850")
    return verdict, score, confidence, [asdict(check) for check in checks], explanation
