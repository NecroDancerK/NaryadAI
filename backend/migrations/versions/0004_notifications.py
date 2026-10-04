"""Deadline notifications."""
from alembic import op
import sqlalchemy as sa

revision = "0004_notifications"
down_revision = "0003_ai_inspection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("work_order_id", "recipient_id", "kind", name="uq_notification_once"),
    )
    op.create_index("ix_notifications_recipient", "notifications", ["recipient_id", "created_at"])


def downgrade() -> None:
    op.drop_table("notifications")
