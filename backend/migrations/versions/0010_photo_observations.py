"""Separate advisory photo observations from repair acceptance and scores."""
from alembic import op
import sqlalchemy as sa

revision = "0010_photo_observations"
down_revision = "0009_completion_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("photo_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("completion_id", sa.Integer(), sa.ForeignKey("work_order_completions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.String(36), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("photo_ids", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.String(300)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("photo_observations")
