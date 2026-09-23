"""House structure and entrance details for the address directory.

Revision ID: 063_geo_gar_entrances
Revises: 062_geo_directory
"""

import sqlalchemy as sa
from alembic import op

revision = "063_geo_gar_entrances"
down_revision = "062_geo_directory"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("geo_houses", sa.Column("structure", sa.String(32), nullable=True))
    op.add_column("geo_entrances", sa.Column("entrance_type", sa.String(32), nullable=True))
    op.add_column("geo_entrances", sa.Column("address_text", sa.String(500), nullable=True))
    op.add_column("geo_entrances", sa.Column("building_osm_id", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("geo_entrances", "building_osm_id")
    op.drop_column("geo_entrances", "address_text")
    op.drop_column("geo_entrances", "entrance_type")
    op.drop_column("geo_houses", "structure")
