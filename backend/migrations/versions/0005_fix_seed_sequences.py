"""Synchronize sequences after explicit seed IDs."""
from alembic import op

revision = "0005_fix_seed_sequences"
down_revision = "0004_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("users", "sites", "equipment", "fault_codes", "materials"):
        op.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1), true)")


def downgrade() -> None:
    pass
