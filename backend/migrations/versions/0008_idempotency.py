"""Persist successful action receipts atomically with order changes."""
import sqlalchemy as sa
from alembic import op

revision = "0008_idempotency"
down_revision = "0007_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("idempotent_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "key", name="uq_idempotent_actor_key"),
    )


def downgrade():
    op.drop_table("idempotent_actions")
