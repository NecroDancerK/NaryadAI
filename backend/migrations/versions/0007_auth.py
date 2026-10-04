"""Add login and PIN credentials."""

import hashlib
import secrets

import sqlalchemy as sa
from alembic import op

revision = "0007_auth"
down_revision = "0006_llm_audit"
branch_labels = None
depends_on = None


def pin_hash(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${salt.hex()}${digest.hex()}"


def upgrade() -> None:
    op.add_column("users", sa.Column("login", sa.String(80), nullable=True))
    op.add_column("users", sa.Column("pin_hash", sa.String(180), nullable=True))
    users = op.get_bind().execute(sa.text("SELECT id, role FROM users ORDER BY id")).mappings()
    credentials = {
        1: ("master", "1111"),
        2: ("worker", "2222"),
        3: ("electrician", "3333"),
    }
    for user in users:
        login, pin = credentials.get(user["id"], (f"worker{user['id']}", "0000"))
        op.get_bind().execute(
            sa.text("UPDATE users SET login=:login, pin_hash=:pin_hash WHERE id=:id"),
            {"login": login, "pin_hash": pin_hash(pin), "id": user["id"]},
        )
    op.alter_column("users", "login", nullable=False)
    op.alter_column("users", "pin_hash", nullable=False)
    op.create_index("ix_users_login", "users", ["login"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_login", table_name="users")
    op.drop_column("users", "pin_hash")
    op.drop_column("users", "login")
