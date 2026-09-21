"""Add IRZ protocol laboratory experiments.

Revision ID: 055_irz_protocol_experiments
Revises: 054_irz_exchange_logs
"""

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "055_irz_protocol_experiments"
down_revision = "054_irz_exchange_logs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "irz_experiments",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imei", sa.String(15), nullable=False),
        sa.Column("command_hex", sa.Text(), nullable=False),
        sa.Column("response_hex", sa.Text(), nullable=False, server_default=""),
        sa.Column("response_ascii", sa.Text(), nullable=False, server_default=""),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_irz_experiments_created_at", "irz_experiments", ["created_at"])
    op.create_index("ix_irz_experiments_deleted_at", "irz_experiments", ["deleted_at"])
    op.create_index("ix_irz_experiments_imei", "irz_experiments", ["imei"])
    op.create_index("ix_irz_experiments_imei_created", "irz_experiments", ["imei", "created_at"])


def downgrade():
    op.drop_table("irz_experiments")
