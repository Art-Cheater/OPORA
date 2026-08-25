"""Галочка «Для Береснева» у заявок.

Revision ID: 033_request_for_beresnev
Revises: 032_personal_contracts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033_request_for_beresnev"
down_revision = "032_personal_contracts"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("requests", "for_beresnev"):
        op.add_column(
            "requests",
            sa.Column(
                "for_beresnev",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.create_index("ix_requests_for_beresnev", "requests", ["for_beresnev"])


def downgrade() -> None:
    if _has_column("requests", "for_beresnev"):
        op.drop_index("ix_requests_for_beresnev", table_name="requests")
        op.drop_column("requests", "for_beresnev")
