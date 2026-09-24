"""Street-lighting poles for the IRZ map.

Revision ID: 067_irz_light_poles
Revises: 066_irz_meter_directory
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "067_irz_light_poles"
down_revision = "066_irz_meter_directory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "light_poles",
        sa.Column("pole_number", sa.String(40), nullable=False),
        sa.Column("luminaire_name", sa.String(500), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_light_poles_pole_number", "light_poles", ["pole_number"], unique=True)
    op.create_index("ix_light_poles_lat_lon", "light_poles", ["latitude", "longitude"])
    op.create_index("ix_light_poles_created_at", "light_poles", ["created_at"])
    op.create_index("ix_light_poles_deleted_at", "light_poles", ["deleted_at"])


def downgrade():
    op.drop_table("light_poles")
