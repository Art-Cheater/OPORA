"""Store last physically read Mercury values and default ATM21 address to zero.

Revision ID: 058_irz_last_mercury_values
Revises: 057_irz_atm21_sessions
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import JSONType

revision = "058_irz_last_mercury_values"
down_revision = "057_irz_atm21_sessions"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("irz_devices") as batch:
        batch.add_column(sa.Column("last_manufacture_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("last_firmware_version", sa.String(40), nullable=True))
        batch.add_column(sa.Column("last_transformation_ratios", JSONType(), nullable=True))
        batch.add_column(sa.Column("last_mercury_seen_at", sa.DateTime(timezone=True), nullable=True))
    # Current production has one physically verified read-only meter behind each
    # known ATM21; address 0 is its confirmed universal/read address.
    op.execute("UPDATE irz_devices SET network_address = 0 WHERE imei IS NOT NULL")


def downgrade():
    with op.batch_alter_table("irz_devices") as batch:
        batch.drop_column("last_mercury_seen_at")
        batch.drop_column("last_transformation_ratios")
        batch.drop_column("last_firmware_version")
        batch.drop_column("last_manufacture_date")
