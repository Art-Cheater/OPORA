"""Таблица прав ролей на уровне полей.

Revision ID: 010_role_field_permissions
Revises: 009_audit_journal
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "010_role_field_permissions"
down_revision = "009_audit_journal"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "role_field_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_role_field_permissions_role_id", "role_field_permissions", ["role_id"])
    op.create_index("ix_role_field_permissions_module", "role_field_permissions", ["module"])


def downgrade():
    op.drop_index("ix_role_field_permissions_module", table_name="role_field_permissions")
    op.drop_index("ix_role_field_permissions_role_id", table_name="role_field_permissions")
    op.drop_table("role_field_permissions")
