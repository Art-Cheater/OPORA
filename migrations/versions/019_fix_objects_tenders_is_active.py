"""Добавляем is_active и TSVECTOR для объектов и заявок на торги.

Revision ID: 019_fix_objects_tenders_is_active
Revises: 018_procurement_chain
Create Date: 2026-08-11

Миграция 018 создала work_objects / tender_applications без is_active,
хотя модели наследуют ActiveRecordMixin — из-за этого списки давали 500.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "019_fix_objects_tenders_is_active"
down_revision = "018_procurement_chain"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in {ix["name"] for ix in insp.get_indexes(table)}


def _column_type_name(table: str, column: str) -> str:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for col in insp.get_columns(table):
        if col["name"] == column:
            return str(col["type"]).lower()
    return ""


def _ensure_tsvector(table: str) -> None:
    """На PostgreSQL: Text → tsvector (данные search_vector ещё не заполнялись)."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if "tsvector" in _column_type_name(table, "search_vector"):
        return
    op.execute(
        sa.text(
            f"ALTER TABLE {table} "
            "ALTER COLUMN search_vector TYPE tsvector USING NULL"
        )
    )


def upgrade() -> None:
    if not _has_column("work_objects", "is_active"):
        op.add_column(
            "work_objects",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    if not _has_index("work_objects", "ix_work_objects_is_active"):
        op.create_index("ix_work_objects_is_active", "work_objects", ["is_active"])

    if not _has_column("tender_applications", "is_active"):
        op.add_column(
            "tender_applications",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    if not _has_index("tender_applications", "ix_tender_applications_is_active"):
        op.create_index(
            "ix_tender_applications_is_active",
            "tender_applications",
            ["is_active"],
        )

    _ensure_tsvector("work_objects")
    _ensure_tsvector("tender_applications")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("work_objects", "tender_applications"):
            if "tsvector" in _column_type_name(table, "search_vector"):
                op.execute(
                    sa.text(
                        f"ALTER TABLE {table} "
                        "ALTER COLUMN search_vector TYPE text USING search_vector::text"
                    )
                )

    if _has_index("tender_applications", "ix_tender_applications_is_active"):
        op.drop_index(
            "ix_tender_applications_is_active",
            table_name="tender_applications",
        )
    if _has_column("tender_applications", "is_active"):
        op.drop_column("tender_applications", "is_active")

    if _has_index("work_objects", "ix_work_objects_is_active"):
        op.drop_index("ix_work_objects_is_active", table_name="work_objects")
    if _has_column("work_objects", "is_active"):
        op.drop_column("work_objects", "is_active")
