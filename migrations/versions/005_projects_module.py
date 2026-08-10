"""Расширение схемы для CRM-модуля проектов.

Revision ID: 005_projects_module
Revises: 004_requests_module
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005_projects_module"
down_revision = "004_requests_module"
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
    op.add_column(
        "projects",
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_projects_progress_percent", "projects", ["progress_percent"], unique=False)

    op.create_table(
        "project_history",
        *AUDIT_COLUMNS,
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False, server_default="update"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_project_history_created_at", "project_history", ["created_at"])
    op.create_index("ix_project_history_deleted_at", "project_history", ["deleted_at"])
    op.create_index("ix_project_history_project_id", "project_history", ["project_id"])
    op.create_index("ix_project_history_changed_by", "project_history", ["changed_by"])

    op.create_table(
        "project_documents",
        *AUDIT_COLUMNS,
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("document_number", sa.String(length=100), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=True),
        sa.Column("storage_key", sa.String(length=1000), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_project_documents_created_at", "project_documents", ["created_at"])
    op.create_index("ix_project_documents_deleted_at", "project_documents", ["deleted_at"])
    op.create_index("ix_project_documents_project_id", "project_documents", ["project_id"])
    op.create_index("ix_project_documents_document_type", "project_documents", ["document_type"])


def downgrade():
    op.drop_index("ix_project_documents_document_type", table_name="project_documents")
    op.drop_index("ix_project_documents_project_id", table_name="project_documents")
    op.drop_index("ix_project_documents_deleted_at", table_name="project_documents")
    op.drop_index("ix_project_documents_created_at", table_name="project_documents")
    op.drop_table("project_documents")

    op.drop_index("ix_project_history_changed_by", table_name="project_history")
    op.drop_index("ix_project_history_project_id", table_name="project_history")
    op.drop_index("ix_project_history_deleted_at", table_name="project_history")
    op.drop_index("ix_project_history_created_at", table_name="project_history")
    op.drop_table("project_history")

    op.drop_index("ix_projects_progress_percent", table_name="projects")
    op.drop_column("projects", "progress_percent")
