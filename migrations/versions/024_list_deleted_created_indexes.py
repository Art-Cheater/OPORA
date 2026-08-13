"""Составные индексы для списков торгов, проектов, договоров и объектов.

Revision ID: 024_list_deleted_created_indexes
Revises: 023_request_list_indexes
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "024_list_deleted_created_indexes"
down_revision = "023_request_list_indexes"
branch_labels = None
depends_on = None


def _indexes(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}
    except Exception:
        return set()


def _create_if_missing(table: str, name: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns)


def _drop_if_exists(table: str, name: str) -> None:
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    _create_if_missing(
        "tender_applications",
        "ix_tender_applications_deleted_created",
        ["deleted_at", "created_at"],
    )
    _create_if_missing("projects", "ix_projects_deleted_created", ["deleted_at", "created_at"])
    _create_if_missing("contracts", "ix_contracts_deleted_created", ["deleted_at", "created_at"])
    _create_if_missing(
        "work_objects",
        "ix_work_objects_deleted_created",
        ["deleted_at", "created_at"],
    )


def downgrade() -> None:
    _drop_if_exists("work_objects", "ix_work_objects_deleted_created")
    _drop_if_exists("contracts", "ix_contracts_deleted_created")
    _drop_if_exists("projects", "ix_projects_deleted_created")
    _drop_if_exists("tender_applications", "ix_tender_applications_deleted_created")
