"""Add the shared address directory and coordinate quality.

Revision ID: 062_geo_directory
Revises: 061_irz_monitoring_dashboard
"""

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "062_geo_directory"
down_revision = "061_irz_monitoring_dashboard"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("requests", sa.Column("geocode_quality", sa.String(16), nullable=True))
    op.add_column("defects", sa.Column("geocode_quality", sa.String(16), nullable=True))
    op.add_column("work_objects", sa.Column("latitude", sa.Numeric(10, 7), nullable=True))
    op.add_column("work_objects", sa.Column("longitude", sa.Numeric(10, 7), nullable=True))
    op.create_index("ix_work_objects_lat_lng", "work_objects", ["latitude", "longitude"])

    op.create_table(
        "geo_settlements",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("name_key", sa.String(255), nullable=False),
        sa.Column("parent_id", GUID(), nullable=True),
        sa.Column("region_name", sa.String(255), nullable=True),
        sa.Column("district_name", sa.String(255), nullable=True),
        sa.Column("fias_id", sa.String(64), nullable=True),
        sa.Column("osm_id", sa.String(64), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_geo_settlements_source_ext"),
    )
    op.create_index("ix_geo_settlements_name_key", "geo_settlements", ["name_key"])
    op.create_index("ix_geo_settlements_deleted_at", "geo_settlements", ["deleted_at"])
    op.create_foreign_key(
        "fk_geo_settlements_parent",
        "geo_settlements",
        "geo_settlements",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "geo_streets",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("settlement_id", GUID(), sa.ForeignKey("geo_settlements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("name_key", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("settlement_name", sa.String(255), nullable=True),
        sa.Column("district_name", sa.String(255), nullable=True),
        sa.Column("region_name", sa.String(255), nullable=True),
        sa.Column("fias_id", sa.String(64), nullable=True),
        sa.Column("osm_id", sa.String(64), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_geo_streets_source_ext"),
    )
    op.create_index("ix_geo_streets_name_key", "geo_streets", ["name_key"])
    op.create_index("ix_geo_streets_deleted_at", "geo_streets", ["deleted_at"])

    op.create_table(
        "geo_houses",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("street_id", GUID(), sa.ForeignKey("geo_streets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("number", sa.String(32), nullable=False),
        sa.Column("number_key", sa.String(32), nullable=False),
        sa.Column("building", sa.String(32), nullable=True),
        sa.Column("postal_code", sa.String(12), nullable=True),
        sa.Column("fias_id", sa.String(64), nullable=True),
        sa.Column("osm_id", sa.String(64), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_geo_houses_source_ext"),
    )
    op.create_index("ix_geo_houses_street_number", "geo_houses", ["street_id", "number_key"])
    op.create_index("ix_geo_houses_deleted_at", "geo_houses", ["deleted_at"])

    op.create_table(
        "geo_entrances",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("house_id", GUID(), sa.ForeignKey("geo_houses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ref", sa.String(32), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("settlement_name", sa.String(255), nullable=True),
        sa.Column("street_name", sa.String(255), nullable=True),
        sa.Column("house_number", sa.String(32), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("osm_id", sa.String(64), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_geo_entrances_source_ext"),
    )
    op.create_index("ix_geo_entrances_lat_lng", "geo_entrances", ["latitude", "longitude"])
    op.create_index("ix_geo_entrances_deleted_at", "geo_entrances", ["deleted_at"])

    op.create_table(
        "geo_geocode_cache",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cache_key", sa.String(400), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("payload", JSONType(), nullable=True),
        sa.UniqueConstraint("cache_key", name="uq_geo_geocode_cache_key"),
    )


def downgrade():
    op.drop_table("geo_geocode_cache")
    op.drop_index("ix_geo_entrances_deleted_at", table_name="geo_entrances")
    op.drop_index("ix_geo_entrances_lat_lng", table_name="geo_entrances")
    op.drop_table("geo_entrances")
    op.drop_index("ix_geo_houses_deleted_at", table_name="geo_houses")
    op.drop_index("ix_geo_houses_street_number", table_name="geo_houses")
    op.drop_table("geo_houses")
    op.drop_index("ix_geo_streets_deleted_at", table_name="geo_streets")
    op.drop_index("ix_geo_streets_name_key", table_name="geo_streets")
    op.drop_table("geo_streets")
    op.drop_constraint("fk_geo_settlements_parent", "geo_settlements", type_="foreignkey")
    op.drop_index("ix_geo_settlements_deleted_at", table_name="geo_settlements")
    op.drop_index("ix_geo_settlements_name_key", table_name="geo_settlements")
    op.drop_table("geo_settlements")
    op.drop_index("ix_work_objects_lat_lng", table_name="work_objects")
    op.drop_column("work_objects", "longitude")
    op.drop_column("work_objects", "latitude")
    op.drop_column("defects", "geocode_quality")
    op.drop_column("requests", "geocode_quality")
