"""Add device inventory and durable TCP command queue.

Revision ID: 050_devices_and_commands
Revises: 049_request_completion
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "050_devices_and_commands"
down_revision = "049_request_completion"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    if "devices" not in existing:
        op.create_table(
            "devices",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), nullable=True),
            sa.Column("updated_by", GUID(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("device_id", sa.String(100), nullable=False, unique=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("secret_encrypted", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("protocol_version", sa.String(32), nullable=False, server_default="1"),
            sa.Column("connection_state", sa.String(24), nullable=False, server_default="offline"),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_ip", sa.String(45), nullable=True),
            sa.Column("actual_state", JSONType(), nullable=True),
            sa.Column("desired_state", JSONType(), nullable=True),
            sa.Column("last_error", sa.String(500), nullable=True),
        )
        op.create_index("ix_devices_connection_state", "devices", ["connection_state"])
        op.create_index("ix_devices_deleted_at", "devices", ["deleted_at"])
    if "device_commands" not in existing:
        op.create_table(
            "device_commands",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), nullable=True),
            sa.Column("updated_by", GUID(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("device_id", GUID(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
            sa.Column("command_id", sa.String(36), nullable=False, unique=True),
            sa.Column("command_type", sa.String(64), nullable=False),
            sa.Column("payload", JSONType(), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
        )
        op.create_index("ix_device_commands_device_status", "device_commands", ["device_id", "status"])
        op.create_index("ix_device_commands_deleted_at", "device_commands", ["deleted_at"])


def downgrade():
    op.drop_table("device_commands")
    op.drop_table("devices")
