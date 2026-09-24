"""Operator mapping from connector pins to U2/U3 bits.

Revision ID: 064_device_phase_input_map
Revises: 063_geo_gar_entrances
"""
import sqlalchemy as sa
from alembic import op

from app.models.types import JSONType

revision = "064_device_phase_input_map"
down_revision = "063_geo_gar_entrances"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("devices", sa.Column("phase_input_map", JSONType(), nullable=True))


def downgrade():
    op.drop_column("devices", "phase_input_map")
