"""Add IRZ monitoring location, poll lease and snapshot metadata.

Revision ID: 061_irz_monitoring_dashboard
Revises: 060_irz_meter_snapshots
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import JSONType

revision = "061_irz_monitoring_dashboard"
down_revision = "060_irz_meter_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("irz_devices", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("irz_devices", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("irz_devices", sa.Column("address_text", sa.String(500), nullable=True))
    op.add_column("irz_devices", sa.Column("poll_lock_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_irz_devices_poll_lock_until", "irz_devices", ["poll_lock_until"])
    op.add_column("irz_meter_snapshots", sa.Column("source", sa.String(16), nullable=False, server_default="MANUAL"))
    op.add_column("irz_meter_snapshots", sa.Column("status", sa.String(20), nullable=False, server_default="SUCCESS"))
    op.add_column("irz_meter_snapshots", sa.Column("extras", JSONType(), nullable=True))


def downgrade():
    op.drop_column("irz_meter_snapshots", "extras")
    op.drop_column("irz_meter_snapshots", "status")
    op.drop_column("irz_meter_snapshots", "source")
    op.drop_index("ix_irz_devices_poll_lock_until", table_name="irz_devices")
    op.drop_column("irz_devices", "poll_lock_until")
    op.drop_column("irz_devices", "address_text")
    op.drop_column("irz_devices", "longitude")
    op.drop_column("irz_devices", "latitude")
