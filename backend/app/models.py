from datetime import datetime

from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.domain import AiVerdict, UserRole, WorkOrderPriority, WorkOrderStatus, WorkOrderType


def enum_values(enum):
    return [item.value for item in enum]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    pin_hash: Mapped[str] = mapped_column(String(180))
    full_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role", values_callable=enum_values))
    specialty: Mapped[str | None] = mapped_column(String(100))
    is_on_shift: Mapped[bool] = mapped_column(Boolean, default=True)


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    inventory_number: Mapped[str] = mapped_column(String(80), unique=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    criticality: Mapped[int] = mapped_column(default=1)


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(30), unique=True)
    work_type: Mapped[WorkOrderType] = mapped_column(Enum(WorkOrderType, name="work_order_type", values_callable=enum_values))
    description: Mapped[str] = mapped_column(Text)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    priority: Mapped[WorkOrderPriority] = mapped_column(Enum(WorkOrderPriority, name="work_order_priority", values_callable=enum_values))
    status: Mapped[WorkOrderStatus] = mapped_column(Enum(WorkOrderStatus, name="work_order_status", values_callable=enum_values), default=WorkOrderStatus.ISSUED, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    events: Mapped[list["WorkOrderEvent"]] = relationship(back_populates="work_order", cascade="all, delete-orphan")


class WorkOrderEvent(Base):
    __tablename__ = "work_order_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    from_status: Mapped[WorkOrderStatus | None] = mapped_column(Enum(WorkOrderStatus, name="work_order_status", values_callable=enum_values))
    to_status: Mapped[WorkOrderStatus] = mapped_column(Enum(WorkOrderStatus, name="work_order_status", values_callable=enum_values))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    work_order: Mapped[WorkOrder] = relationship(back_populates="events")


class FaultCode(Base):
    __tablename__ = "fault_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(30))


class WorkOrderCompletion(Base):
    __tablename__ = "work_order_completions"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), unique=True)
    fault_code_id: Mapped[int] = mapped_column(ForeignKey("fault_codes.id"))
    work_performed: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    completed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaterialUsage(Base):
    __tablename__ = "material_usages"
    id: Mapped[int] = mapped_column(primary_key=True)
    completion_id: Mapped[int] = mapped_column(ForeignKey("work_order_completions.id", ondelete="CASCADE"))
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))


class WorkOrderPhoto(Base):
    __tablename__ = "work_order_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"))
    photo_type: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiInspection(Base):
    __tablename__ = "ai_inspections"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), unique=True)
    verdict: Mapped[AiVerdict] = mapped_column(Enum(AiVerdict, name="ai_verdict", values_callable=enum_values))
    score: Mapped[int]
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    checks: Mapped[list[dict]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    analysis_source: Mapped[str] = mapped_column(String(40), default="rules")
    model_name: Mapped[str | None] = mapped_column(String(200))
    llm_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"))
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
