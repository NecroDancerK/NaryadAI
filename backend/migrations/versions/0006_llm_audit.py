"""Record AI inspection source and model."""
from alembic import op
import sqlalchemy as sa

revision = "0006_llm_audit"
down_revision = "0005_fix_seed_sequences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_inspections", sa.Column("analysis_source", sa.String(40), nullable=False, server_default="rules"))
    op.add_column("ai_inspections", sa.Column("model_name", sa.String(200), nullable=True))
    op.add_column("ai_inspections", sa.Column("llm_error", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_inspections", "llm_error")
    op.drop_column("ai_inspections", "model_name")
    op.drop_column("ai_inspections", "analysis_source")
