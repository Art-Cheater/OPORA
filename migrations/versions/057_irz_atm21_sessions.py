"""Correct IRZ devices to represent inbound ATM21 sessions.

Revision ID: 057_irz_atm21_sessions
Revises: 056_irz_mercury_operator
"""
import sqlalchemy as sa
from alembic import op

revision = "057_irz_atm21_sessions"
down_revision = "056_irz_mercury_operator"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("irz_exchange_logs") as batch:
        batch.add_column(sa.Column("packet_type", sa.String(32), nullable=True))
        batch.create_index("ix_irz_exchange_logs_packet_type", ["packet_type"])
    with op.batch_alter_table("irz_devices") as batch:
        batch.add_column(sa.Column("imei", sa.String(15), nullable=True))
        batch.add_column(sa.Column("device_type", sa.String(20), nullable=True))
        batch.add_column(sa.Column("firmware_version", sa.String(20), nullable=True))
        batch.add_column(sa.Column("firmware_revision", sa.String(20), nullable=True))
        batch.add_column(sa.Column("firmware_build", sa.String(40), nullable=True))
        batch.add_column(sa.Column("hardware_version", sa.String(20), nullable=True))
        batch.add_column(sa.Column("sim", sa.String(40), nullable=True))
        batch.add_column(sa.Column("csq", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("atp", sa.String(20), nullable=True))
        batch.add_column(sa.Column("interfaces", sa.String(40), nullable=True))
        batch.add_column(sa.Column("last_ip", sa.String(45), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        batch.alter_column("transport_type", existing_type=sa.String(10), nullable=True)
        batch.alter_column("network_address", existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint("ck_irz_devices_transport", type_="check")
        batch.drop_constraint("ck_irz_devices_state", type_="check")
        batch.create_unique_constraint("uq_irz_devices_imei", ["imei"])
        batch.create_index("ix_irz_devices_imei", ["imei"])


def downgrade():
    with op.batch_alter_table("irz_devices") as batch:
        batch.drop_index("ix_irz_devices_imei")
        batch.drop_constraint("uq_irz_devices_imei", type_="unique")
        for column in ("last_seen_at", "last_ip", "interfaces", "atp", "csq", "sim", "hardware_version",
                       "firmware_build", "firmware_revision", "firmware_version", "device_type", "imei"):
            batch.drop_column(column)
        batch.alter_column("transport_type", existing_type=sa.String(10), nullable=False)
        batch.alter_column("network_address", existing_type=sa.Integer(), nullable=False)
        batch.create_check_constraint("ck_irz_devices_transport", "transport_type IN ('SERIAL', 'TCP')")
        batch.create_check_constraint("ck_irz_devices_state", "connection_state IN ('DISCONNECTED', 'CONNECTING', 'CONNECTED', 'BUSY', 'ERROR')")
    with op.batch_alter_table("irz_exchange_logs") as batch:
        batch.drop_index("ix_irz_exchange_logs_packet_type")
        batch.drop_column("packet_type")
