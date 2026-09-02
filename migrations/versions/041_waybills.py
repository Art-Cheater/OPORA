"""Путевые листы, точки маршрута и состав.

Revision ID: 041_waybills
Revises: 040_request_defects
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType, SearchVectorType

revision = "041_waybills"
down_revision = "040_request_defects"
branch_labels = None
depends_on = None

WAYBILL_TRIGGER = """
CREATE OR REPLACE FUNCTION waybills_search_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('simple', coalesce(NEW.number, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce(NEW.comment, '')), 'B');
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
    if not _has_table("waybills"):
        op.create_table(
            "waybills",
            *_base_columns(),
            sa.Column("number", sa.String(length=50), nullable=False),
            sa.Column("work_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("search_vector", SearchVectorType(), nullable=True),
            sa.Column("master_id", GUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        )
        op.create_index("ix_waybills_deleted_at", "waybills", ["deleted_at"])
        op.create_index("ix_waybills_number", "waybills", ["number"], unique=True)
        op.create_index("ix_waybills_master_id", "waybills", ["master_id"])
        op.create_index("ix_waybills_status", "waybills", ["status"])
        op.create_index("ix_waybills_work_date", "waybills", ["work_date"])
        op.create_index("ix_waybills_deleted_created", "waybills", ["deleted_at", "created_at"])

    if not _has_table("waybill_stops"):
        op.create_table(
            "waybill_stops",
            *_base_columns(),
            sa.Column("waybill_id", GUID(), sa.ForeignKey("waybills.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("request_id", GUID(), sa.ForeignKey("requests.id", ondelete="CASCADE"), nullable=True),
            sa.Column("defect_id", GUID(), sa.ForeignKey("defects.id", ondelete="CASCADE"), nullable=True),
            sa.Column("address", sa.String(length=500), nullable=False),
            sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
            sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "(request_id IS NOT NULL AND defect_id IS NULL) "
                "OR (request_id IS NULL AND defect_id IS NOT NULL)",
                name="ck_waybill_stops_one_target",
            ),
        )
        op.create_index("ix_waybill_stops_deleted_at", "waybill_stops", ["deleted_at"])
        op.create_index("ix_waybill_stops_waybill_id", "waybill_stops", ["waybill_id"])
        op.create_index("ix_waybill_stops_request_id", "waybill_stops", ["request_id"])
        op.create_index("ix_waybill_stops_defect_id", "waybill_stops", ["defect_id"])
        op.create_index(
            "uq_waybill_stops_order",
            "waybill_stops",
            ["waybill_id", "sort_order"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    if not _has_table("waybill_members"):
        op.create_table(
            "waybill_members",
            *_base_columns(),
            sa.Column("waybill_id", GUID(), sa.ForeignKey("waybills.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        )
        op.create_index("ix_waybill_members_deleted_at", "waybill_members", ["deleted_at"])
        op.create_index("ix_waybill_members_waybill_id", "waybill_members", ["waybill_id"])
        op.create_index("ix_waybill_members_user_id", "waybill_members", ["user_id"])
        op.create_index(
            "uq_waybill_members_user",
            "waybill_members",
            ["waybill_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    if not _has_table("waybill_history"):
        op.create_table(
            "waybill_history",
            *_base_columns(),
            sa.Column("waybill_id", GUID(), sa.ForeignKey("waybills.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action", sa.String(length=50), nullable=False, server_default="update"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("details", JSONType(), nullable=True),
            sa.Column("changed_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_waybill_history_deleted_at", "waybill_history", ["deleted_at"])
        op.create_index("ix_waybill_history_waybill_id", "waybill_history", ["waybill_id"])
        op.create_index("ix_waybill_history_changed_by", "waybill_history", ["changed_by"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and _has_table("waybills"):
        op.execute(WAYBILL_TRIGGER)
        op.execute("DROP TRIGGER IF EXISTS trg_waybills_search_vector ON waybills")
        op.execute(
            """
            CREATE TRIGGER trg_waybills_search_vector
            BEFORE INSERT OR UPDATE ON waybills
            FOR EACH ROW EXECUTE FUNCTION waybills_search_vector_update()
            """
        )
        op.execute("UPDATE waybills SET number = number")
        existing_indexes = {ix["name"] for ix in sa.inspect(bind).get_indexes("waybills")}
        if "ix_waybills_search_vector_gin" not in existing_indexes:
            op.create_index(
                "ix_waybills_search_vector_gin",
                "waybills",
                ["search_vector"],
                unique=False,
                postgresql_using="gin",
            )


def downgrade() -> None:
    pass
