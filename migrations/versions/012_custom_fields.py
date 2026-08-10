"""Пользовательские поля (EAV).

Revision ID: 012_custom_fields
Revises: 011_rbac_catalog
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "012_custom_fields"
down_revision = "011_rbac_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "custom_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("field_type", sa.String(30), nullable=False, server_default="text"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_custom_fields_module_id", "custom_fields", ["module_id"])

    op.create_table(
        "field_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("custom_field_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", sa.String(100), nullable=False),
        sa.Column("label", sa.String(150), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["custom_field_id"], ["custom_fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_field_options_custom_field_id", "field_options", ["custom_field_id"])

    op.create_table(
        "custom_field_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("custom_field_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["custom_field_id"], ["custom_fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_custom_field_values_entity", "custom_field_values", ["entity_type", "entity_id"])
    op.create_index("ix_custom_field_values_custom_field_id", "custom_field_values", ["custom_field_id"])
    op.create_index("ix_custom_field_values_value_text", "custom_field_values", ["value_text"])


def downgrade():
    op.drop_index("ix_custom_field_values_value_text", table_name="custom_field_values")
    op.drop_index("ix_custom_field_values_custom_field_id", table_name="custom_field_values")
    op.drop_index("ix_custom_field_values_entity", table_name="custom_field_values")
    op.drop_table("custom_field_values")
    op.drop_index("ix_field_options_custom_field_id", table_name="field_options")
    op.drop_table("field_options")
    op.drop_index("ix_custom_fields_module_id", table_name="custom_fields")
    op.drop_table("custom_fields")
