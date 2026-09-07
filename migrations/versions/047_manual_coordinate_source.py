"""Track whether Request/Defect coordinates were set manually or by a geocoder.

Revision ID: 047_manual_coordinate_source
Revises: 046_push_subscriptions_defect_reported_at
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "047_manual_coordinate_source"
down_revision = "046_push_subscriptions_defect_reported_at"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table in ("requests", "defects"):
        if "coordinates_source" not in {item["name"] for item in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("coordinates_source", sa.String(length=20), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    for table in ("defects", "requests"):
        if "coordinates_source" in {item["name"] for item in inspector.get_columns(table)}:
            op.drop_column(table, "coordinates_source")
