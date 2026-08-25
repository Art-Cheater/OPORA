"""Частичный индекс непрочитанных сообщений мессенджера.

Revision ID: 031_messenger_unread_idx
Revises: 030_inquiry_forward
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "031_messenger_unread_idx"
down_revision = "030_inquiry_forward"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_messenger_messages_is_read")
        op.create_index(
            "ix_messenger_messages_unread_conv",
            "messenger_messages",
            ["conversation_id"],
            unique=False,
            postgresql_where=sa.text("is_read = false AND deleted_at IS NULL"),
        )
    else:
        # SQLite: partial index для тестов
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_messenger_messages_unread_conv "
            "ON messenger_messages (conversation_id) "
            "WHERE is_read = 0 AND deleted_at IS NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_messenger_messages_unread_conv")
        op.create_index(
            "ix_messenger_messages_is_read",
            "messenger_messages",
            ["is_read"],
            unique=False,
        )
    else:
        op.execute("DROP INDEX IF EXISTS ix_messenger_messages_unread_conv")
