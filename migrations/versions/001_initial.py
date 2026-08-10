"""Полная схема БД системы «Опора»

Revision ID: 001_initial
Revises:
Create Date: 2026-08-06

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

# Общие колонки аудита для всех таблиц
AUDIT_COLUMNS = [
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
]


def _audit_fks(table_name: str) -> list:
    return [
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=f"fk_{table_name}_created_by_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=f"fk_{table_name}_updated_by_users", ondelete="SET NULL"
        ),
    ]


def upgrade():
    # ── users ──────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_users_created_at", "users", ["created_at"])
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])
    op.create_index("ix_users_full_name", "users", ["full_name"])
    op.create_index("ix_users_is_active", "users", ["is_active"])
    op.create_index(
        "ix_users_email_unique_active",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── roles ──────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        *AUDIT_COLUMNS,
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_audit_fks("roles"),
    )
    op.create_index("ix_roles_created_at", "roles", ["created_at"])
    op.create_index("ix_roles_deleted_at", "roles", ["deleted_at"])
    op.create_index("ix_roles_name", "roles", ["name"])
    op.create_index(
        "ix_roles_code_unique_active",
        "roles",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── permissions ──────────────────────────────────────────────────────
    op.create_table(
        "permissions",
        *AUDIT_COLUMNS,
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_audit_fks("permissions"),
    )
    op.create_index("ix_permissions_created_at", "permissions", ["created_at"])
    op.create_index("ix_permissions_deleted_at", "permissions", ["deleted_at"])
    op.create_index("ix_permissions_module", "permissions", ["module"])
    op.create_index(
        "ix_permissions_code_unique_active",
        "permissions",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── user_roles ─────────────────────────────────────────────────────
    op.create_table(
        "user_roles",
        *AUDIT_COLUMNS,
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        *_audit_fks("user_roles"),
    )
    op.create_index("ix_user_roles_created_at", "user_roles", ["created_at"])
    op.create_index("ix_user_roles_deleted_at", "user_roles", ["deleted_at"])
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])
    op.create_index(
        "ix_user_roles_unique_active",
        "user_roles",
        ["user_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── role_permissions ───────────────────────────────────────────────
    op.create_table(
        "role_permissions",
        *AUDIT_COLUMNS,
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        *_audit_fks("role_permissions"),
    )
    op.create_index("ix_role_permissions_created_at", "role_permissions", ["created_at"])
    op.create_index("ix_role_permissions_deleted_at", "role_permissions", ["deleted_at"])
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])
    op.create_index(
        "ix_role_permissions_unique_active",
        "role_permissions",
        ["role_id", "permission_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── request_statuses ───────────────────────────────────────────────
    op.create_table(
        "request_statuses",
        *AUDIT_COLUMNS,
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(20), nullable=False, server_default="#6c757d"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_audit_fks("request_statuses"),
    )
    op.create_index("ix_request_statuses_created_at", "request_statuses", ["created_at"])
    op.create_index("ix_request_statuses_deleted_at", "request_statuses", ["deleted_at"])
    op.create_index("ix_request_statuses_sort_order", "request_statuses", ["sort_order"])
    op.create_index(
        "ix_request_statuses_code_unique_active",
        "request_statuses",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── projects ───────────────────────────────────────────────────────
    op.create_table(
        "projects",
        *AUDIT_COLUMNS,
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="SET NULL"),
        *_audit_fks("projects"),
    )
    op.create_index("ix_projects_created_at", "projects", ["created_at"])
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"])
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_projects_manager_id", "projects", ["manager_id"])
    op.create_index("ix_projects_start_date", "projects", ["start_date"])
    op.create_index(
        "ix_projects_code_unique_active",
        "projects",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── project_members ────────────────────────────────────────────────
    op.create_table(
        "project_members",
        *AUDIT_COLUMNS,
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_in_project", sa.String(30), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        *_audit_fks("project_members"),
    )
    op.create_index("ix_project_members_created_at", "project_members", ["created_at"])
    op.create_index("ix_project_members_deleted_at", "project_members", ["deleted_at"])
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.create_index(
        "ix_project_members_unique_active",
        "project_members",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── requests ───────────────────────────────────────────────────────
    op.create_table(
        "requests",
        *AUDIT_COLUMNS,
        sa.Column("number", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["status_id"], ["request_statuses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        *_audit_fks("requests"),
    )
    op.create_index("ix_requests_created_at", "requests", ["created_at"])
    op.create_index("ix_requests_deleted_at", "requests", ["deleted_at"])
    op.create_index("ix_requests_number", "requests", ["number"], unique=True)
    op.create_index("ix_requests_status_id", "requests", ["status_id"])
    op.create_index("ix_requests_project_id", "requests", ["project_id"])
    op.create_index("ix_requests_assignee_id", "requests", ["assignee_id"])
    op.create_index("ix_requests_priority", "requests", ["priority"])
    op.create_index("ix_requests_due_date", "requests", ["due_date"])

    # ── request_history ──────────────────────────────────────────────────
    op.create_table(
        "request_history",
        *AUDIT_COLUMNS,
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["status_id"], ["request_statuses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_status_id"], ["request_statuses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        *_audit_fks("request_history"),
    )
    op.create_index("ix_request_history_created_at", "request_history", ["created_at"])
    op.create_index("ix_request_history_deleted_at", "request_history", ["deleted_at"])
    op.create_index("ix_request_history_request_id", "request_history", ["request_id"])
    op.create_index("ix_request_history_status_id", "request_history", ["status_id"])
    op.create_index("ix_request_history_changed_by", "request_history", ["changed_by"])

    # ── contracts ────────────────────────────────────────────────────────
    op.create_table(
        "contracts",
        *AUDIT_COLUMNS,
        sa.Column("number", sa.String(100), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contractor_name", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="RUB"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        *_audit_fks("contracts"),
    )
    op.create_index("ix_contracts_created_at", "contracts", ["created_at"])
    op.create_index("ix_contracts_deleted_at", "contracts", ["deleted_at"])
    op.create_index("ix_contracts_project_id", "contracts", ["project_id"])
    op.create_index("ix_contracts_status", "contracts", ["status"])
    op.create_index("ix_contracts_start_date", "contracts", ["start_date"])
    op.create_index(
        "ix_contracts_number_unique_active",
        "contracts",
        ["number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── messages ───────────────────────────────────────────────────────
    op.create_table(
        "messages",
        *AUDIT_COLUMNS,
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["messages.id"], ondelete="SET NULL"),
        *_audit_fks("messages"),
    )
    op.create_index("ix_messages_created_at", "messages", ["created_at"])
    op.create_index("ix_messages_deleted_at", "messages", ["deleted_at"])
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])
    op.create_index("ix_messages_recipient_id", "messages", ["recipient_id"])
    op.create_index("ix_messages_parent_id", "messages", ["parent_id"])
    op.create_index("ix_messages_is_read", "messages", ["is_read"])

    # ── notifications ──────────────────────────────────────────────────
    op.create_table(
        "notifications",
        *AUDIT_COLUMNS,
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False, server_default="info"),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("link", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        *_audit_fks("notifications"),
    )
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index("ix_notifications_deleted_at", "notifications", ["deleted_at"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_is_read", "notifications", ["is_read"])
    op.create_index("ix_notifications_entity", "notifications", ["entity_type", "entity_id"])
    op.create_index("ix_notifications_type", "notifications", ["type"])

    # ── comments ───────────────────────────────────────────────────────
    op.create_table(
        "comments",
        *AUDIT_COLUMNS,
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["comments.id"], ondelete="SET NULL"),
        *_audit_fks("comments"),
    )
    op.create_index("ix_comments_created_at", "comments", ["created_at"])
    op.create_index("ix_comments_deleted_at", "comments", ["deleted_at"])
    op.create_index("ix_comments_entity", "comments", ["entity_type", "entity_id"])
    op.create_index("ix_comments_author_id", "comments", ["author_id"])
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"])

    # ── attachments ────────────────────────────────────────────────────
    op.create_table(
        "attachments",
        *AUDIT_COLUMNS,
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("storage_key", sa.String(1000), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        *_audit_fks("attachments"),
    )
    op.create_index("ix_attachments_created_at", "attachments", ["created_at"])
    op.create_index("ix_attachments_deleted_at", "attachments", ["deleted_at"])
    op.create_index("ix_attachments_entity", "attachments", ["entity_type", "entity_id"])
    op.create_index("ix_attachments_uploaded_by", "attachments", ["uploaded_by"])
    op.create_index("ix_attachments_file_name", "attachments", ["file_name"])

    # ── audit_log ──────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        *AUDIT_COLUMNS,
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_values", postgresql.JSONB(), nullable=True),
        sa.Column("new_values", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        *_audit_fks("audit_log"),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_deleted_at", "audit_log", ["deleted_at"])
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])


def downgrade():
    op.drop_table("audit_log")
    op.drop_table("attachments")
    op.drop_table("comments")
    op.drop_table("notifications")
    op.drop_table("messages")
    op.drop_table("contracts")
    op.drop_table("request_history")
    op.drop_table("requests")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("request_statuses")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
