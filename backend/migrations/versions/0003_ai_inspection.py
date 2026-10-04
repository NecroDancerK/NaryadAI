"""AI inspection reports."""
from alembic import op
import sqlalchemy as sa

revision = "0003_ai_inspection"
down_revision = "0002_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    verdict = sa.Enum("accepted", "accepted_with_comments", "rework", name="ai_verdict")
    op.create_table("ai_inspections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("verdict", verdict, nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ai_inspections")
    sa.Enum(name="ai_verdict").drop(op.get_bind(), checkfirst=True)
