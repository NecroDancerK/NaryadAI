"""Account blocking, session revocation and administrative audit."""
import sqlalchemy as sa
from alembic import op

revision = "0011_user_management"
down_revision = "0010_photo_observations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("uq_users_login_lower", "users", [sa.text("lower(login)")], unique=True)
    op.create_table("admin_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("admin_audit")
    op.drop_index("uq_users_login_lower", table_name="users")
    op.drop_column("users", "session_version")
    op.drop_column("users", "is_active")
