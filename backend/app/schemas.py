from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.domain import UserRole, WorkOrderPriority, WorkOrderStatus, WorkOrderType


class AuthLogin(BaseModel):
    login: str = Field(min_length=2, max_length=80)
    pin: str = Field(pattern=r"^\d{4,8}$")


class CurrentUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    login: str
    full_name: str
    role: UserRole
    specialty: str | None


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: CurrentUserRead


class WorkOrderCreate(BaseModel):
    description: str = Field(min_length=5, max_length=4000)
    work_type: WorkOrderType
    site_id: int
    equipment_id: int
    assignee_id: int
    priority: WorkOrderPriority
    due_at: datetime


class WorkOrderTransition(BaseModel):
    status: WorkOrderStatus
    comment: str | None = Field(default=None, max_length=2000)


class WorkOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    number: str
    description: str
    work_type: WorkOrderType
    site_id: int
    equipment_id: int
    assignee_id: int
    master_id: int
    priority: WorkOrderPriority
    status: WorkOrderStatus
    due_at: datetime
    created_at: datetime


class WorkOrderEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    actor_id: int
    from_status: WorkOrderStatus | None
    to_status: WorkOrderStatus
    comment: str | None
    created_at: datetime


class AiInspectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    verdict: str
    score: int
    confidence: float
    checks: list[dict]
    explanation: str
    analysis_source: str
    model_name: str | None
    llm_error: str | None
    created_at: datetime


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    work_order_id: int
    recipient_id: int
    kind: str
    title: str
    message: str
    is_read: bool
    created_at: datetime
