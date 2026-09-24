"""Mercury serial -> ШУНО reference and IRZ directory match state.

Revision ID: 066_irz_meter_directory
Revises: 065_device_input_test_log
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "066_irz_meter_directory"
down_revision = "065_device_input_test_log"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meter_cabinet_directory",
        sa.Column("meter_serial", sa.String(40), nullable=False),
        sa.Column("cabinet_name", sa.String(160), nullable=True),
        sa.Column("cabinet_external_id", sa.String(40), nullable=True),
        sa.Column("meter_model", sa.String(120), nullable=True),
        sa.Column("installed_at", sa.Date(), nullable=True),
        sa.Column("installed_raw", sa.String(60), nullable=True),
        sa.Column("ktt", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meter_cabinet_directory_meter_serial", "meter_cabinet_directory", ["meter_serial"], unique=True)
    op.create_index("ix_meter_cabinet_directory_created_at", "meter_cabinet_directory", ["created_at"])
    op.create_index("ix_meter_cabinet_directory_deleted_at", "meter_cabinet_directory", ["deleted_at"])

    op.add_column("irz_devices", sa.Column("directory_entry_id", GUID(), nullable=True))
    op.add_column("irz_devices", sa.Column("directory_match_status", sa.String(24), nullable=True))
    op.add_column("irz_devices", sa.Column("directory_match_serial", sa.String(40), nullable=True))
    op.add_column("irz_devices", sa.Column("directory_matched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_irz_devices_directory_entry_id", "irz_devices", ["directory_entry_id"])
    op.add_column("irz_meters", sa.Column("catalog_model", sa.String(120), nullable=True))


def downgrade():
    op.drop_column("irz_meters", "catalog_model")
    op.drop_index("ix_irz_devices_directory_entry_id", table_name="irz_devices")
    op.drop_column("irz_devices", "directory_matched_at")
    op.drop_column("irz_devices", "directory_match_serial")
    op.drop_column("irz_devices", "directory_match_status")
    op.drop_column("irz_devices", "directory_entry_id")
    op.drop_table("meter_cabinet_directory")
