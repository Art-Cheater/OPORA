"""Расширить url в журнале ЕИС — длинные ссылки zakupki.

Revision ID: 034_eis_event_url_len
Revises: 033_request_for_beresnev
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034_eis_event_url_len"
down_revision = "033_request_for_beresnev"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def upgrade() -> None:
    if _has_column("eis_import_events", "url"):
        op.alter_column(
            "eis_import_events",
            "url",
            existing_type=sa.String(length=700),
            type_=sa.String(length=2000),
            existing_nullable=True,
        )


def downgrade() -> None:
    if _has_column("eis_import_events", "url"):
        op.alter_column(
            "eis_import_events",
            "url",
            existing_type=sa.String(length=2000),
            type_=sa.String(length=700),
            existing_nullable=True,
        )
