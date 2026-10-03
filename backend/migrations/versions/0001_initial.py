"""Initial work-order domain."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = sa.Enum("master", "worker", "manager", "admin", name="user_role")
    order_status = sa.Enum("issued", "accepted", "queued", "rejected", "in_progress", "paused", "completed", "ai_review", "rework", "closed", name="work_order_status")
    priority = sa.Enum("emergency", "high", "normal", "planned", name="work_order_priority")
    work_type = sa.Enum("planned", "unplanned", name="work_order_type")
    op.create_table("users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("role", role, nullable=False),
        sa.Column("specialty", sa.String(100)),
        sa.Column("is_on_shift", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table("sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
    )
    op.create_table("equipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("inventory_number", sa.String(80), nullable=False, unique=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("criticality", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table("work_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(30), nullable=False, unique=True),
        sa.Column("work_type", work_type, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("equipment_id", sa.Integer(), sa.ForeignKey("equipment.id"), nullable=False),
        sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("master_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("priority", priority, nullable=False),
        sa.Column("status", order_status, nullable=False, server_default="issued"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table("work_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("from_status", order_status, nullable=True),
        sa.Column("to_status", order_status, nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_work_orders_status", "work_orders", ["status"])
    op.create_index("ix_work_orders_assignee_id", "work_orders", ["assignee_id"])
    op.create_index("ix_work_order_events_work_order_id", "work_order_events", ["work_order_id"])

    users = sa.table("users", sa.column("id", sa.Integer), sa.column("full_name", sa.String), sa.column("role", role), sa.column("specialty", sa.String), sa.column("is_on_shift", sa.Boolean))
    sites = sa.table("sites", sa.column("id", sa.Integer), sa.column("name", sa.String))
    equipment = sa.table("equipment", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("inventory_number", sa.String), sa.column("site_id", sa.Integer), sa.column("criticality", sa.Integer))
    op.bulk_insert(users, [
        {"id": 1, "full_name": "Сергеев Алексей", "role": "master", "specialty": None, "is_on_shift": True},
        {"id": 2, "full_name": "Ахметов Ерлан", "role": "worker", "specialty": "Слесарь", "is_on_shift": True},
        {"id": 3, "full_name": "Ким Андрей", "role": "worker", "specialty": "Электрик", "is_on_shift": True},
    ])
    op.bulk_insert(sites, [{"id": 1, "name": "Участок дробления"}, {"id": 2, "name": "Участок обогащения"}])
    op.bulk_insert(equipment, [
        {"id": 1, "name": "Дробилка КМД-1750", "inventory_number": "ДР-001", "site_id": 1, "criticality": 3},
        {"id": 2, "name": "Конвейер К-3", "inventory_number": "КН-003", "site_id": 1, "criticality": 2},
        {"id": 3, "name": "Насос Н-12", "inventory_number": "НС-012", "site_id": 2, "criticality": 3},
    ])


def downgrade() -> None:
    op.drop_table("work_order_events")
    op.drop_table("work_orders")
    op.drop_table("equipment")
    op.drop_table("sites")
    op.drop_table("users")
    for enum_name in ("work_order_type", "work_order_priority", "work_order_status", "user_role"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
