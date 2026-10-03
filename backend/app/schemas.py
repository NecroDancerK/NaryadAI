from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.domain import WorkOrderPriority, WorkOrderStatus, WorkOrderType


class WorkOrderCreate(BaseModel):
    description: str = Field(min_length=5, max_length=4000)
    work_type: WorkOrderType
    site_id: int
    equipment_id: int
    assignee_id: int
    master_id: int
    priority: WorkOrderPriority
    due_at: datetime


class WorkOrderTransition(BaseModel):
    actor_id: int
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
