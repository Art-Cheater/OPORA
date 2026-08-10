"""Поля заявки: ПП, дата получения, диспетчер + справочник диспетчеров.

Revision ID: 015_request_pp_dispatcher
Revises: 014_field_definition_visible
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015_request_pp_dispatcher"
down_revision = "014_field_definition_visible"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("pp", sa.String(length=255), nullable=True))
    op.add_column(
        "requests",
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "requests",
        sa.Column("dispatcher_name", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_requests_received_at", "requests", ["received_at"])
    op.create_index("ix_requests_dispatcher_name", "requests", ["dispatcher_name"])

    # backfill: дата получения = created_at
    op.execute(sa.text("UPDATE requests SET received_at = created_at WHERE received_at IS NULL"))

    op.create_table(
        "request_dispatchers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_request_dispatchers_sort_order", "request_dispatchers", ["sort_order"])
    op.create_index(
        "ix_request_dispatchers_is_active",
        "request_dispatchers",
        ["is_active"],
    )
    op.create_index(
        "ix_request_dispatchers_deleted_at",
        "request_dispatchers",
        ["deleted_at"],
    )


def downgrade() -> None:
    op.drop_table("request_dispatchers")
    op.drop_index("ix_requests_dispatcher_name", table_name="requests")
    op.drop_index("ix_requests_received_at", table_name="requests")
    op.drop_column("requests", "dispatcher_name")
    op.drop_column("requests", "received_at")
    op.drop_column("requests", "pp")
