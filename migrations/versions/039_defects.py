"""Дефекты: статусы, категории, карточки, история, FTS.

Revision ID: 039_defects
Revises: 038_request_journals
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from app.models.types import GUID, JSONType, SearchVectorType
from app.modules.defects.workflow import DEFECT_CATEGORIES, DEFECT_STATUSES

revision = "039_defects"
down_revision = "038_request_journals"
branch_labels = None
depends_on = None

STATUS_NS = uuid.UUID("a91c4e22-7d18-4b6f-b3a1-0c8e5d4f2a11")
CATEGORY_NS = uuid.UUID("b02d5f33-8e29-4c70-c4b2-1d9f6e5a3b22")

DEFECT_TRIGGER = """
CREATE OR REPLACE FUNCTION defects_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', coalesce(NEW.number, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.address, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.description, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _insp().get_table_names()


def _base_columns():
    return [
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    if not _has_table("defect_statuses"):
        op.create_table(
            "defect_statuses",
            *_base_columns(),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("color", sa.String(length=20), nullable=False, server_default="#6c757d"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("ix_defect_statuses_deleted_at", "defect_statuses", ["deleted_at"])
        op.create_index("ix_defect_statuses_sort_order", "defect_statuses", ["sort_order"])
        op.create_index("ix_defect_statuses_is_active", "defect_statuses", ["is_active"])
        op.create_index(
            "ix_defect_statuses_code_unique_active",
            "defect_statuses",
            ["code"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    if not _has_table("defect_categories"):
        op.create_table(
            "defect_categories",
            *_base_columns(),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_defect_categories_deleted_at", "defect_categories", ["deleted_at"])
        op.create_index("ix_defect_categories_sort_order", "defect_categories", ["sort_order"])
        op.create_index("ix_defect_categories_is_active", "defect_categories", ["is_active"])
        op.create_index(
            "ix_defect_categories_code_unique_active",
            "defect_categories",
            ["code"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    now = datetime.now(timezone.utc)
    bind = op.get_bind()
    existing_status = {row[0] for row in bind.execute(sa.text("SELECT code FROM defect_statuses WHERE deleted_at IS NULL"))}
    status_table = sa.table(
        "defect_statuses",
        sa.column("id", GUID()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("is_active", sa.Boolean()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("color", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_final", sa.Boolean()),
    )
    status_rows = []
    for code, name, desc, color, order, is_final in DEFECT_STATUSES:
        if code in existing_status:
            continue
        status_rows.append(
            {
                "id": uuid.uuid5(STATUS_NS, code),
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
                "is_active": True,
                "code": code,
                "name": name,
                "description": desc,
                "color": color,
                "sort_order": order,
                "is_final": is_final,
            }
        )
    if status_rows:
        op.bulk_insert(status_table, status_rows)

    existing_cat = {row[0] for row in bind.execute(sa.text("SELECT code FROM defect_categories WHERE deleted_at IS NULL"))}
    cat_table = sa.table(
        "defect_categories",
        sa.column("id", GUID()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("is_active", sa.Boolean()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    cat_rows = []
    for code, name, sort_order in DEFECT_CATEGORIES:
        if code in existing_cat:
            continue
        cat_rows.append(
            {
                "id": uuid.uuid5(CATEGORY_NS, code),
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
                "is_active": True,
                "code": code,
                "name": name,
                "sort_order": sort_order,
            }
        )
    if cat_rows:
        op.bulk_insert(cat_table, cat_rows)

    if not _has_table("defects"):
        op.create_table(
            "defects",
            *_base_columns(),
            sa.Column("number", sa.String(length=50), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("address", sa.String(length=500), nullable=False),
            sa.Column("original_address", sa.String(length=500), nullable=True),
            sa.Column("normalized_address", sa.String(length=1000), nullable=True),
            sa.Column("region", sa.String(length=255), nullable=True),
            sa.Column("district", sa.String(length=255), nullable=True),
            sa.Column("settlement", sa.String(length=255), nullable=True),
            sa.Column("street", sa.String(length=500), nullable=True),
            sa.Column("house", sa.String(length=100), nullable=True),
            sa.Column("address_source", sa.String(length=50), nullable=True),
            sa.Column("address_external_id", sa.String(length=255), nullable=True),
            sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
            sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
            sa.Column("search_vector", SearchVectorType(), nullable=True),
            sa.Column("status_id", GUID(), sa.ForeignKey("defect_statuses.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("category_id", GUID(), sa.ForeignKey("defect_categories.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("responsible_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_defects_deleted_at", "defects", ["deleted_at"])
        op.create_index("ix_defects_number", "defects", ["number"], unique=True)
        op.create_index("ix_defects_status_id", "defects", ["status_id"])
        op.create_index("ix_defects_category_id", "defects", ["category_id"])
        op.create_index("ix_defects_responsible_id", "defects", ["responsible_id"])
        op.create_index("ix_defects_address", "defects", ["address"])
        op.create_index("ix_defects_district", "defects", ["district"])
        op.create_index("ix_defects_settlement", "defects", ["settlement"])
        op.create_index("ix_defects_street_district", "defects", ["street", "district"])
        op.create_index("ix_defects_normalized_address", "defects", ["normalized_address"])
        op.create_index("ix_defects_lat_lng", "defects", ["latitude", "longitude"])
        op.create_index("ix_defects_deleted_created", "defects", ["deleted_at", "created_at"])
        op.create_index("ix_defects_deleted_status", "defects", ["deleted_at", "status_id"])

    if not _has_table("defect_history"):
        op.create_table(
            "defect_history",
            *_base_columns(),
            sa.Column("defect_id", GUID(), sa.ForeignKey("defects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status_id", GUID(), sa.ForeignKey("defect_statuses.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("previous_status_id", GUID(), sa.ForeignKey("defect_statuses.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=50), nullable=False, server_default="update"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("details", JSONType(), nullable=True),
            sa.Column("changed_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_defect_history_deleted_at", "defect_history", ["deleted_at"])
        op.create_index("ix_defect_history_defect_id", "defect_history", ["defect_id"])
        op.create_index("ix_defect_history_status_id", "defect_history", ["status_id"])
        op.create_index("ix_defect_history_changed_by", "defect_history", ["changed_by"])

    if bind.dialect.name == "postgresql":
        op.execute(DEFECT_TRIGGER)
        op.execute("DROP TRIGGER IF EXISTS trg_defects_search_vector ON defects")
        op.execute(
            """
            CREATE TRIGGER trg_defects_search_vector
            BEFORE INSERT OR UPDATE ON defects
            FOR EACH ROW EXECUTE FUNCTION defects_search_vector_update()
            """
        )
        op.execute("UPDATE defects SET number = number")
        existing_indexes = {ix["name"] for ix in sa.inspect(bind).get_indexes("defects")}
        if "ix_defects_search_vector_gin" not in existing_indexes:
            op.create_index(
                "ix_defects_search_vector_gin",
                "defects",
                ["search_vector"],
                unique=False,
                postgresql_using="gin",
            )


def downgrade() -> None:
    pass
