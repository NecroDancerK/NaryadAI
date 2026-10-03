from enum import StrEnum


class UserRole(StrEnum):
    MASTER = "master"
    WORKER = "worker"
    MANAGER = "manager"
    ADMIN = "admin"


class WorkOrderStatus(StrEnum):
    ISSUED = "issued"
    ACCEPTED = "accepted"
    QUEUED = "queued"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    AI_REVIEW = "ai_review"
    REWORK = "rework"
    CLOSED = "closed"


class WorkOrderPriority(StrEnum):
    EMERGENCY = "emergency"
    HIGH = "high"
    NORMAL = "normal"
    PLANNED = "planned"


class WorkOrderType(StrEnum):
    PLANNED = "planned"
    UNPLANNED = "unplanned"


ALLOWED_TRANSITIONS: dict[WorkOrderStatus, frozenset[WorkOrderStatus]] = {
    WorkOrderStatus.ISSUED: frozenset({WorkOrderStatus.ACCEPTED, WorkOrderStatus.QUEUED, WorkOrderStatus.REJECTED}),
    WorkOrderStatus.ACCEPTED: frozenset({WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.QUEUED}),
    WorkOrderStatus.QUEUED: frozenset({WorkOrderStatus.ACCEPTED}),
    WorkOrderStatus.REJECTED: frozenset({WorkOrderStatus.ISSUED}),
    WorkOrderStatus.IN_PROGRESS: frozenset({WorkOrderStatus.PAUSED, WorkOrderStatus.COMPLETED}),
    WorkOrderStatus.PAUSED: frozenset({WorkOrderStatus.IN_PROGRESS}),
    WorkOrderStatus.COMPLETED: frozenset({WorkOrderStatus.AI_REVIEW}),
    WorkOrderStatus.AI_REVIEW: frozenset({WorkOrderStatus.REWORK, WorkOrderStatus.CLOSED}),
    WorkOrderStatus.REWORK: frozenset({WorkOrderStatus.IN_PROGRESS}),
    WorkOrderStatus.CLOSED: frozenset(),
}


def can_transition(current: WorkOrderStatus, target: WorkOrderStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
