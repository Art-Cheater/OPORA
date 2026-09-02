"""Журналы заявок и нумерация внутри журнала.

Revision ID: 038_request_journals
Revises: 037_wallpapers
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID
from app.modules.requests.journals import REQUEST_JOURNALS

revision = "038_request_journals"
down_revision = "037_wallpapers"
branch_labels = None
depends_on = None

JOURNAL_NS = uuid.UUID("8b6d1f3e-2c4a-4d91-9a0b-7e5c1d2a3b4f")


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _insp().get_table_names()


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in _insp().get_columns(table))


def _has_index(table: str, name: str) -> bool:
    return any(ix.get("name") == name for ix in _insp().get_indexes(table))


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
    if not _has_table("request_journals"):
        op.create_table(
            "request_journals",
            *_base_columns(),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index("ix_request_journals_deleted_at", "request_journals", ["deleted_at"])
        op.create_index("ix_request_journals_sort_order", "request_journals", ["sort_order"])
        op.create_index("ix_request_journals_is_active", "request_journals", ["is_active"])
        op.create_index(
            "ix_request_journals_code_unique_active",
            "request_journals",
            ["code"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    journals = sa.table(
        "request_journals",
        sa.column("id", GUID()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("is_active", sa.Boolean()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    now = datetime.now(timezone.utc)
    bind = op.get_bind()
    existing_codes = {row[0] for row in bind.execute(sa.text("SELECT code FROM request_journals WHERE deleted_at IS NULL"))}
    rows = []
    for code, name, sort_order in REQUEST_JOURNALS:
        if code in existing_codes:
            continue
        rows.append(
            {
                "id": uuid.uuid5(JOURNAL_NS, code),
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
                "is_active": True,
                "code": code,
                "name": name,
                "sort_order": sort_order,
            }
        )
    if rows:
        op.bulk_insert(journals, rows)

    if not _has_table("request_journal_counters"):
        op.create_table(
            "request_journal_counters",
            *_base_columns(),
            sa.Column("journal_id", GUID(), sa.ForeignKey("request_journals.id", ondelete="CASCADE"), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("journal_id", "year", name="uq_request_journal_counters_journal_year"),
        )
        op.create_index("ix_request_journal_counters_deleted_at", "request_journal_counters", ["deleted_at"])
        op.create_index("ix_request_journal_counters_journal_id", "request_journal_counters", ["journal_id"])

    main_id = uuid.uuid5(JOURNAL_NS, "requests")
    if not _has_column("requests", "journal_id"):
        op.add_column("requests", sa.Column("journal_id", GUID(), nullable=True))
        op.create_foreign_key(
            "fk_requests_journal_id_request_journals",
            "requests",
            "request_journals",
            ["journal_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.execute(
        sa.text("UPDATE requests SET journal_id = :jid WHERE journal_id IS NULL").bindparams(jid=main_id)
    )
    op.alter_column("requests", "journal_id", existing_type=GUID(), nullable=False)

    if _has_index("requests", "ix_requests_number"):
        op.drop_index("ix_requests_number", table_name="requests")
    if not _has_index("requests", "uq_requests_journal_number"):
        op.create_index("uq_requests_journal_number", "requests", ["journal_id", "number"], unique=True)
    if not _has_index("requests", "ix_requests_journal_id"):
        op.create_index("ix_requests_journal_id", "requests", ["journal_id"])
    if not _has_index("requests", "ix_requests_street_district"):
        op.create_index("ix_requests_street_district", "requests", ["street", "district"])
    if not _has_index("requests", "ix_requests_normalized_address"):
        op.create_index("ix_requests_normalized_address", "requests", ["normalized_address"])
    if not _has_index("requests", "ix_requests_lat_lng"):
        op.create_index("ix_requests_lat_lng", "requests", ["latitude", "longitude"])
    if not _has_index("requests", "ix_requests_deleted_journal_received"):
        op.create_index(
            "ix_requests_deleted_journal_received",
            "requests",
            ["deleted_at", "journal_id", "received_at"],
        )


def downgrade() -> None:
    pass
