"""Связь заявка ↔ дефект.

Revision ID: 040_request_defects
Revises: 039_defects
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "040_request_defects"
down_revision = "039_defects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "request_defects" in insp.get_table_names():
        return
    op.create_table(
        "request_defects",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", GUID(), sa.ForeignKey("requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("defect_id", GUID(), sa.ForeignKey("defects.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_request_defects_deleted_at", "request_defects", ["deleted_at"])
    op.create_index("ix_request_defects_request_id", "request_defects", ["request_id"])
    op.create_index("ix_request_defects_defect_id", "request_defects", ["defect_id"])
    op.create_index(
        "uq_request_defects_pair",
        "request_defects",
        ["request_id", "defect_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    pass
