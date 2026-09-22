"""Add Mercury devices and structured operation journal.

Revision ID: 056_irz_mercury_operator
Revises: 055_irz_protocol_experiments
"""

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "056_irz_mercury_operator"
down_revision = "055_irz_protocol_experiments"
branch_labels = None
depends_on = None


def _base_columns():
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade():
    op.create_table(
        "irz_devices",
        *_base_columns(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("model", sa.String(40), nullable=False, server_default="Mercury V2"),
        sa.Column("serial_number", sa.String(40), nullable=True),
        sa.Column("network_address", sa.Integer(), nullable=False),
        sa.Column("transport_type", sa.String(10), nullable=False),
        sa.Column("serial_port", sa.String(255), nullable=True),
        sa.Column("host", sa.String(253), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("baudrate", sa.Integer(), nullable=False, server_default="9600"),
        sa.Column("connection_params", JSONType(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("connection_state", sa.String(16), nullable=False, server_default="DISCONNECTED"),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("transport_type IN ('SERIAL', 'TCP')", name="ck_irz_devices_transport"),
        sa.CheckConstraint("connection_state IN ('DISCONNECTED', 'CONNECTING', 'CONNECTED', 'BUSY', 'ERROR')", name="ck_irz_devices_state"),
    )
    for name, columns in (
        ("ix_irz_devices_created_at", ["created_at"]),
        ("ix_irz_devices_deleted_at", ["deleted_at"]),
        ("ix_irz_devices_enabled", ["enabled"]),
        ("ix_irz_devices_connection_state", ["connection_state"]),
        ("ix_irz_devices_enabled_name", ["enabled", "name"]),
    ):
        op.create_index(name, "irz_devices", columns)

    op.create_table(
        "irz_operation_logs",
        *_base_columns(),
        sa.Column("device_id", GUID(), sa.ForeignKey("irz_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("command_id", sa.String(80), nullable=False),
        sa.Column("mercury_command", sa.String(120), nullable=True),
        sa.Column("operation", sa.String(20), nullable=False, server_default="COMMAND"),
        sa.Column("request_parameters", JSONType(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("result", JSONType(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("tx_raw", sa.Text(), nullable=True),
        sa.Column("rx_raw", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('SUCCESS', 'ERROR', 'TIMEOUT')", name="ck_irz_operation_logs_status"),
    )
    for name, columns in (
        ("ix_irz_operation_logs_created_at", ["created_at"]),
        ("ix_irz_operation_logs_deleted_at", ["deleted_at"]),
        ("ix_irz_operation_logs_device_id", ["device_id"]),
        ("ix_irz_operation_logs_user_id", ["user_id"]),
        ("ix_irz_operation_logs_device_created", ["device_id", "created_at"]),
        ("ix_irz_operation_logs_status_created", ["status", "created_at"]),
    ):
        op.create_index(name, "irz_operation_logs", columns)


def downgrade():
    op.drop_table("irz_operation_logs")
    op.drop_table("irz_devices")
