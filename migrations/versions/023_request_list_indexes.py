"""Индексы для списков и отчётов по заявкам.

Revision ID: 023_request_list_indexes
Revises: 022_request_address_metadata
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "023_request_list_indexes"
down_revision = "022_request_address_metadata"
branch_labels = None
depends_on = None


def _indexes(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}
    except Exception:
        return set()


def upgrade() -> None:
    request_indexes = _indexes("requests")
    if "ix_requests_deleted_received" not in request_indexes:
        op.create_index("ix_requests_deleted_received", "requests", ["deleted_at", "received_at"])
    if "ix_requests_deleted_status" not in request_indexes:
        op.create_index("ix_requests_deleted_status", "requests", ["deleted_at", "status_id"])

    history_indexes = _indexes("request_history")
    if "ix_request_history_status_created" not in history_indexes:
        op.create_index(
            "ix_request_history_status_created",
            "request_history",
            ["status_id", "created_at"],
        )


def downgrade() -> None:
    history_indexes = _indexes("request_history")
    if "ix_request_history_status_created" in history_indexes:
        op.drop_index("ix_request_history_status_created", table_name="request_history")

    request_indexes = _indexes("requests")
    if "ix_requests_deleted_status" in request_indexes:
        op.drop_index("ix_requests_deleted_status", table_name="requests")
    if "ix_requests_deleted_received" in request_indexes:
        op.drop_index("ix_requests_deleted_received", table_name="requests")
