"""Add persisted IRZ ATM21 exchange log.

Revision ID: 054_irz_exchange_logs
Revises: 053_device_diagnostic_mode
"""

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "054_irz_exchange_logs"
down_revision = "053_device_diagnostic_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "irz_exchange_logs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imei", sa.String(15), nullable=True),
        sa.Column("direction", sa.String(2), nullable=False),
        sa.Column("raw_hex", sa.Text(), nullable=False),
        sa.Column("raw_ascii", sa.Text(), nullable=False),
        sa.Column("raw_length", sa.Integer(), nullable=False),
        sa.CheckConstraint("direction IN ('RX', 'TX')", name="ck_irz_exchange_logs_direction"),
    )
    op.create_index("ix_irz_exchange_logs_created_at", "irz_exchange_logs", ["created_at"])
    op.create_index("ix_irz_exchange_logs_deleted_at", "irz_exchange_logs", ["deleted_at"])
    op.create_index("ix_irz_exchange_logs_imei", "irz_exchange_logs", ["imei"])
    op.create_index("ix_irz_exchange_logs_imei_created", "irz_exchange_logs", ["imei", "created_at"])


def downgrade():
    op.drop_table("irz_exchange_logs")
