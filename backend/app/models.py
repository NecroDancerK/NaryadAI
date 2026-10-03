from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.domain import UserRole, WorkOrderPriority, WorkOrderStatus, WorkOrderType


def enum_values(enum):
    return [item.value for item in enum]


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
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
