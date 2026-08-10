"""Поле reply_to_id для ответов в мессенджере.

Revision ID: 016_messenger_reply
Revises: 015_request_pp_dispatcher
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "016_messenger_reply"
down_revision = "015_request_pp_dispatcher"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messenger_messages",
        sa.Column("reply_to_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_messenger_messages_reply_to_id",
        "messenger_messages",
        "messenger_messages",
        ["reply_to_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_messenger_messages_reply_to_id",
        "messenger_messages",
        ["reply_to_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_messenger_messages_reply_to_id", table_name="messenger_messages")
    op.drop_constraint(
        "fk_messenger_messages_reply_to_id",
        "messenger_messages",
        type_="foreignkey",
    )
    op.drop_column("messenger_messages", "reply_to_id")
