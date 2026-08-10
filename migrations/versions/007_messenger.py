"""Схема корпоративного мессенджера.

Revision ID: 007_messenger
Revises: 006_contracts_module
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "007_messenger"
down_revision = "006_contracts_module"
branch_labels = None
depends_on = None

AUDIT_COLUMNS = [
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade():
    op.create_table(
        "messenger_conversations",
        *AUDIT_COLUMNS,
        sa.Column("participant_a_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_b_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["participant_a_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_b_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_messenger_conversations_created_at", "messenger_conversations", ["created_at"])
    op.create_index("ix_messenger_conversations_deleted_at", "messenger_conversations", ["deleted_at"])
    op.create_index("ix_messenger_conversations_participant_a", "messenger_conversations", ["participant_a_id"])
    op.create_index("ix_messenger_conversations_participant_b", "messenger_conversations", ["participant_b_id"])
    op.create_index("ix_messenger_conversations_last_message_at", "messenger_conversations", ["last_message_at"])
    op.create_index(
        "ix_messenger_conversations_unique_pair",
        "messenger_conversations",
        ["participant_a_id", "participant_b_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "messenger_messages",
        *AUDIT_COLUMNS,
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=True),
        sa.Column("storage_key", sa.String(length=1000), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["messenger_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_messenger_messages_created_at", "messenger_messages", ["created_at"])
    op.create_index("ix_messenger_messages_deleted_at", "messenger_messages", ["deleted_at"])
    op.create_index("ix_messenger_messages_conversation_id", "messenger_messages", ["conversation_id"])
    op.create_index("ix_messenger_messages_sender_id", "messenger_messages", ["sender_id"])
    op.create_index("ix_messenger_messages_is_read", "messenger_messages", ["is_read"])

    op.create_table(
        "user_presence",
        *AUDIT_COLUMNS,
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_user_presence_created_at", "user_presence", ["created_at"])
    op.create_index("ix_user_presence_deleted_at", "user_presence", ["deleted_at"])
    op.create_index(
        "ix_user_presence_user_id_unique",
        "user_presence",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # permission messenger.use
    op.execute(
        sa.text(
            """
            INSERT INTO permissions (id, created_at, updated_at, code, name, module, is_active)
            SELECT gen_random_uuid(), NOW(), NOW(), 'messenger.use', 'Использование мессенджера', 'messenger', true
            WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'messenger.use' AND deleted_at IS NULL)
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, created_at, updated_at, role_id, permission_id)
            SELECT gen_random_uuid(), NOW(), NOW(), r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND p.code = 'messenger.use'
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted_at IS NULL
              )
            """
        )
    )


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = 'messenger.use')"
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE code = 'messenger.use'"))

    op.drop_index("ix_user_presence_user_id_unique", table_name="user_presence")
    op.drop_index("ix_user_presence_deleted_at", table_name="user_presence")
    op.drop_index("ix_user_presence_created_at", table_name="user_presence")
    op.drop_table("user_presence")

    op.drop_index("ix_messenger_messages_is_read", table_name="messenger_messages")
    op.drop_index("ix_messenger_messages_sender_id", table_name="messenger_messages")
    op.drop_index("ix_messenger_messages_conversation_id", table_name="messenger_messages")
    op.drop_index("ix_messenger_messages_deleted_at", table_name="messenger_messages")
    op.drop_index("ix_messenger_messages_created_at", table_name="messenger_messages")
    op.drop_table("messenger_messages")

    op.drop_index("ix_messenger_conversations_unique_pair", table_name="messenger_conversations")
    op.drop_index("ix_messenger_conversations_last_message_at", table_name="messenger_conversations")
    op.drop_index("ix_messenger_conversations_participant_b", table_name="messenger_conversations")
    op.drop_index("ix_messenger_conversations_participant_a", table_name="messenger_conversations")
    op.drop_index("ix_messenger_conversations_deleted_at", table_name="messenger_conversations")
    op.drop_index("ix_messenger_conversations_created_at", table_name="messenger_conversations")
    op.drop_table("messenger_conversations")
