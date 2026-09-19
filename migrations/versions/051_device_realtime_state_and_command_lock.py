"""Add realtime controller state and one-active-command invariant.

Revision ID: 051_device_realtime_state_and_command_lock
Revises: 050_devices_and_commands
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import JSONType


revision = "051_device_realtime_state_and_command_lock"
down_revision = "050_devices_and_commands"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade():
    columns = _columns("devices")
    if "telemetry" not in columns:
        op.add_column("devices", sa.Column("telemetry", JSONType(), nullable=True))
    if "last_state_at" not in columns:
        op.add_column("devices", sa.Column("last_state_at", sa.DateTime(timezone=True), nullable=True))

    columns = _columns("device_commands")
    if "state_confirmed_at" not in columns:
        op.add_column("device_commands", sa.Column("state_confirmed_at", sa.DateTime(timezone=True), nullable=True))

    # Existing queues from the pre-serialization UI can contain several active
    # commands. Keep the oldest one and fail later conflicting commands.
    op.execute(
        """
        UPDATE device_commands
        SET status = 'failed', failed_at = CURRENT_TIMESTAMP,
            error = 'Superseded by per-device command serialization migration'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY device_id ORDER BY created_at, id
                ) AS row_num
                FROM device_commands
                WHERE deleted_at IS NULL AND status IN ('pending', 'sent')
            ) duplicate_commands
            WHERE row_num > 1
        )
        """
    )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("device_commands")}
    if "uq_device_commands_one_active_per_device" not in indexes:
        active_condition = sa.text("deleted_at IS NULL AND status IN ('pending', 'sent')")
        op.create_index(
            "uq_device_commands_one_active_per_device",
            "device_commands",
            ["device_id"],
            unique=True,
            postgresql_where=active_condition,
            sqlite_where=active_condition,
        )


def downgrade():
    op.drop_index("uq_device_commands_one_active_per_device", table_name="device_commands")
    op.drop_column("device_commands", "state_confirmed_at")
    op.drop_column("devices", "last_state_at")
    op.drop_column("devices", "telemetry")
