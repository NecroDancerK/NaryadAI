"""Preserve submission history and bind photos/inspections to a submission."""
from alembic import op
import sqlalchemy as sa

revision = "0009_completion_history"
down_revision = "0008_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("work_order_completions_work_order_id_key", "work_order_completions", type_="unique")
    op.create_index("ix_work_order_completions_work_order_id", "work_order_completions", ["work_order_id"])
    op.drop_constraint("ai_inspections_work_order_id_key", "ai_inspections", type_="unique")
    op.create_index("ix_ai_inspections_work_order_id", "ai_inspections", ["work_order_id"])
    for table in ("work_order_photos", "ai_inspections"):
        op.add_column(table, sa.Column("completion_id", sa.Integer(), nullable=True))
        op.create_foreign_key(f"fk_{table}_completion", table, "work_order_completions", ["completion_id"], ["id"], ondelete="CASCADE")
        condition = " AND target.photo_type = 'after'" if table == "work_order_photos" else ""
        op.execute(sa.text(f"UPDATE {table} AS target SET completion_id = c.id FROM work_order_completions c WHERE c.work_order_id = target.work_order_id{condition}"))
    op.create_index("ix_work_order_photos_completion_id", "work_order_photos", ["completion_id"])
    op.create_unique_constraint("ai_inspections_completion_id_key", "ai_inspections", ["completion_id"])


def downgrade() -> None:
    # Refuse a lossy downgrade instead of silently deleting earlier submissions.
    bind = op.get_bind()
    for table in ("work_order_completions", "ai_inspections"):
        duplicate = bind.execute(sa.text(f"SELECT 1 FROM {table} GROUP BY work_order_id HAVING count(*) > 1 LIMIT 1")).first()
        if duplicate:
            raise RuntimeError("Cannot downgrade: multiple submissions exist; preserve/export history first")
    op.drop_constraint("ai_inspections_completion_id_key", "ai_inspections", type_="unique")
    op.drop_index("ix_work_order_photos_completion_id", table_name="work_order_photos")
    for table in ("work_order_photos", "ai_inspections"):
        op.drop_constraint(f"fk_{table}_completion", table, type_="foreignkey")
        op.drop_column(table, "completion_id")
    for table in ("work_order_completions", "ai_inspections"):
        op.drop_index(f"ix_{table}_work_order_id", table_name=table)
        op.create_unique_constraint(f"{table}_work_order_id_key", table, ["work_order_id"])
