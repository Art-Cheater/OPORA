"""Личные договоры и флаг включения в профиле пользователя.

Revision ID: 032_personal_contracts
Revises: 031_messenger_unread_idx
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "032_personal_contracts"
down_revision = "031_messenger_unread_idx"
branch_labels = None
depends_on = None


def _guid():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.Uuid()


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("users", "personal_contracts_enabled"):
        op.add_column(
            "users",
            sa.Column(
                "personal_contracts_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _has_table("personal_contracts"):
        op.create_table(
            "personal_contracts",
            sa.Column("id", _guid(), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", _guid(), nullable=True),
            sa.Column("updated_by", _guid(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("user_id", _guid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "attachment_id",
                _guid(),
                sa.ForeignKey("attachments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("ends_on", sa.Date(), nullable=True),
            sa.Column(
                "reminders_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("reminded_month_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reminded_two_weeks_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_personal_contracts_user_id", "personal_contracts", ["user_id"])
        op.create_index("ix_personal_contracts_ends_on", "personal_contracts", ["ends_on"])
        op.create_index(
            "ix_personal_contracts_attachment_id",
            "personal_contracts",
            ["attachment_id"],
            unique=True,
        )


def downgrade() -> None:
    if _has_table("personal_contracts"):
        op.drop_table("personal_contracts")
    if _has_column("users", "personal_contracts_enabled"):
        op.drop_column("users", "personal_contracts_enabled")
