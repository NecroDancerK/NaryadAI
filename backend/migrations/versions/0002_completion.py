"""Work-order completion details, materials and photos."""
from alembic import op
import sqlalchemy as sa

revision = "0002_completion"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("fault_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
    )
    op.create_table("materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
    )
    op.create_table("work_order_completions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("fault_code_id", sa.Integer(), sa.ForeignKey("fault_codes.id"), nullable=False),
        sa.Column("work_performed", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("completed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table("material_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("completion_id", sa.Integer(), sa.ForeignKey("work_order_completions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("materials.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_material_usage_positive"),
    )
    op.create_table("work_order_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("photo_type", sa.String(20), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("original_name", sa.String(255)),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    fault_codes = sa.table("fault_codes", sa.column("id", sa.Integer), sa.column("code", sa.String), sa.column("name", sa.String))
    materials = sa.table("materials", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("unit", sa.String))
    op.bulk_insert(fault_codes, [
        {"id": 1, "code": "М-01", "name": "Механический износ"},
        {"id": 2, "code": "М-02", "name": "Подшипник"},
        {"id": 3, "code": "Э-01", "name": "Электрическая неисправность"},
        {"id": 4, "code": "Г-01", "name": "Утечка гидравлической жидкости"},
        {"id": 5, "code": "С-01", "name": "Недостаточная смазка"},
    ])
    op.bulk_insert(materials, [
        {"id": 1, "name": "Масло индустриальное", "unit": "л"},
        {"id": 2, "name": "Подшипник 6205", "unit": "шт"},
        {"id": 3, "name": "Ветошь", "unit": "кг"},
        {"id": 4, "name": "Уплотнительное кольцо", "unit": "шт"},
        {"id": 5, "name": "Кабель силовой", "unit": "м"},
    ])


def downgrade() -> None:
    op.drop_table("work_order_photos")
    op.drop_table("material_usages")
    op.drop_table("work_order_completions")
    op.drop_table("materials")
    op.drop_table("fault_codes")
