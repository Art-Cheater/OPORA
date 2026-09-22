"""Persist physically discovered Mercury meters and latest read-only snapshot.

Revision ID: 059_irz_meter_identity
Revises: 058_irz_last_mercury_values
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "059_irz_meter_identity"
down_revision = "058_irz_last_mercury_values"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "irz_meters",
        sa.Column("irz_device_id", GUID(), sa.ForeignKey("irz_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("serial_number", sa.String(40), nullable=False),
        sa.Column("custom_name", sa.String(160), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("model_source", sa.String(20), nullable=True),
        sa.Column("manufacture_date", sa.Date(), nullable=True),
        sa.Column("firmware_version", sa.String(40), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_status", sa.String(20), nullable=True),
        sa.Column("latest_snapshot", JSONType(), nullable=True),
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("serial_number", name="uq_irz_meters_serial_number"),
    )
    op.create_index("ix_irz_meters_irz_device_id", "irz_meters", ["irz_device_id"])
    op.create_index("ix_irz_meters_serial_number", "irz_meters", ["serial_number"])
    op.create_index("ix_irz_meters_device_seen", "irz_meters", ["irz_device_id", "last_seen_at"])
    op.create_index("ix_irz_meters_created_at", "irz_meters", ["created_at"])
    op.create_index("ix_irz_meters_deleted_at", "irz_meters", ["deleted_at"])


def downgrade():
    op.drop_table("irz_meters")
