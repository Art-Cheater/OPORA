"""Store one telemetry row per logical Mercury poll.

Revision ID: 060_irz_meter_snapshots
Revises: 059_irz_meter_identity
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "060_irz_meter_snapshots"
down_revision = "059_irz_meter_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "irz_meter_snapshots",
        sa.Column("meter_id", GUID(), sa.ForeignKey("irz_meters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("values", JSONType(), nullable=False),
        sa.Column("quality", sa.String(20), nullable=False),
        sa.Column("quality_flags", JSONType(), nullable=True),
        sa.Column("poll_duration_ms", sa.Integer(), nullable=True),
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_irz_meter_snapshots_meter_captured", "irz_meter_snapshots", ["meter_id", "captured_at"])
    op.create_index("ix_irz_meter_snapshots_captured", "irz_meter_snapshots", ["captured_at"])
    op.create_index("ix_irz_meter_snapshots_created_at", "irz_meter_snapshots", ["created_at"])
    op.create_index("ix_irz_meter_snapshots_deleted_at", "irz_meter_snapshots", ["deleted_at"])


def downgrade():
    op.drop_table("irz_meter_snapshots")
