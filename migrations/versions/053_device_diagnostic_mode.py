"""Add opt-in controller diagnostic snapshots.

Revision ID: 053_device_diagnostic_mode
Revises: 052_device_acknowledgement_confirmation_lock
"""
import sqlalchemy as sa
from alembic import op
from app.models.types import GUID
revision = "053_device_diagnostic_mode"
down_revision = "052_device_acknowledgement_confirmation_lock"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("devices", sa.Column("diagnostic_mode", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("device_diagnostic_samples", sa.Column("id", GUID(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_by", GUID()), sa.Column("updated_by", GUID()), sa.Column("deleted_at", sa.DateTime(timezone=True)), sa.Column("device_id", GUID(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False), sa.Column("outputs_mask", sa.Integer()), sa.Column("raw_u2", sa.String(2)), sa.Column("raw_u3", sa.String(2)), sa.Column("csq", sa.String(32)), sa.Column("creg", sa.String(32)), sa.Column("cgatt", sa.String(32)))
    op.create_table("device_diagnostic_events", sa.Column("id", GUID(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_by", GUID()), sa.Column("updated_by", GUID()), sa.Column("deleted_at", sa.DateTime(timezone=True)), sa.Column("device_id", GUID(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False), sa.Column("text", sa.String(500), nullable=False))
def downgrade():
    op.drop_table("device_diagnostic_events"); op.drop_table("device_diagnostic_samples"); op.drop_column("devices", "diagnostic_mode")
