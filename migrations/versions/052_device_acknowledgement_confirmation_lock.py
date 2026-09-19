"""Keep an ACKed command active until device state confirms it.

Revision ID: 052_device_acknowledgement_confirmation_lock
Revises: 051_device_realtime_state_and_command_lock
"""

from alembic import op
import sqlalchemy as sa


revision = "052_device_acknowledgement_confirmation_lock"
down_revision = "051_device_realtime_state_and_command_lock"
branch_labels = None
depends_on = None


_INDEX = "uq_device_commands_one_active_per_device"
_CONDITION = sa.text(
    "deleted_at IS NULL AND (status IN ('pending', 'sent') "
    "OR (status = 'acknowledged' AND state_confirmed_at IS NULL))"
)


def upgrade():
    # Earlier releases treated every ACK as terminal. They can therefore
    # contain several ACKed-but-unconfirmed commands for one device. Keep the
    # oldest pending lifecycle and close later historical entries before the
    # stricter unique index is created.
    op.execute(
        """
        UPDATE device_commands
        SET status = 'failed', failed_at = CURRENT_TIMESTAMP,
            error = 'Superseded by state-confirmation serialization migration'
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY device_id ORDER BY created_at, id
                ) AS row_num
                FROM device_commands
                WHERE deleted_at IS NULL
                  AND (status IN ('pending', 'sent')
                       OR (status = 'acknowledged' AND state_confirmed_at IS NULL))
            ) duplicate_commands
            WHERE row_num > 1
        )
        """
    )
    op.drop_index(_INDEX, table_name="device_commands")
    op.create_index(
        _INDEX,
        "device_commands",
        ["device_id"],
        unique=True,
        postgresql_where=_CONDITION,
        sqlite_where=_CONDITION,
    )


def downgrade():
    op.drop_index(_INDEX, table_name="device_commands")
    old_condition = sa.text("deleted_at IS NULL AND status IN ('pending', 'sent')")
    op.create_index(
        _INDEX,
        "device_commands",
        ["device_id"],
        unique=True,
        postgresql_where=old_condition,
        sqlite_where=old_condition,
    )
