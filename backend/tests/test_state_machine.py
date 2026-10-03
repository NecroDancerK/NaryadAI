import pytest
from app.domain import WorkOrderStatus, can_transition


@pytest.mark.parametrize("source,target", [
    (WorkOrderStatus.ISSUED, WorkOrderStatus.ACCEPTED),
    (WorkOrderStatus.ISSUED, WorkOrderStatus.QUEUED),
    (WorkOrderStatus.ACCEPTED, WorkOrderStatus.IN_PROGRESS),
    (WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.PAUSED),
    (WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.COMPLETED),
    (WorkOrderStatus.COMPLETED, WorkOrderStatus.AI_REVIEW),
    (WorkOrderStatus.AI_REVIEW, WorkOrderStatus.REWORK),
    (WorkOrderStatus.AI_REVIEW, WorkOrderStatus.CLOSED),
])
def test_allowed_transitions(source, target):
    assert can_transition(source, target)


@pytest.mark.parametrize("source,target", [
    (WorkOrderStatus.ISSUED, WorkOrderStatus.CLOSED),
    (WorkOrderStatus.ACCEPTED, WorkOrderStatus.COMPLETED),
    (WorkOrderStatus.CLOSED, WorkOrderStatus.IN_PROGRESS),
])
def test_forbidden_transitions(source, target):
    assert not can_transition(source, target)
