"""Additional map points for complex Request/Defect addresses.

Revision ID: 048_work_map_points
Revises: 047_manual_coordinate_source
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op
from app.models.types import GUID

revision = "048_work_map_points"
down_revision = "047_manual_coordinate_source"
branch_labels = None
depends_on = None

def upgrade():
    if "work_map_points" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "work_map_points",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID()),
        sa.Column("updated_by", GUID()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", GUID(), nullable=False),
        sa.Column("address_part", sa.String(1000), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("confidence", sa.String(30), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_work_map_points_entity", "work_map_points", ["entity_type", "entity_id"])
    op.create_index("ix_work_map_points_lat_lng", "work_map_points", ["latitude", "longitude"])

def downgrade():
    if "work_map_points" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("work_map_points")
