"""RBAC: модули, поля, должности, расширенные разрешения.

Revision ID: 011_rbac_catalog
Revises: 010_role_field_permissions
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "011_rbac_catalog"
down_revision = "010_role_field_permissions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_modules_code_unique_active", "modules", ["code"], unique=True)
    op.create_index("ix_modules_sort_order", "modules", ["sort_order"])

    op.create_table(
        "fields",
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
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_fields_module_id", "fields", ["module_id"])

    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_positions_code_unique_active", "positions", ["code"], unique=True)

    with op.batch_alter_table("permissions") as batch_op:
        batch_op.add_column(sa.Column("action", sa.String(50), nullable=False, server_default="view"))
        batch_op.add_column(sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_permissions_module_id_modules",
            "modules",
            ["module_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_permissions_module_id", ["module_id"])
        batch_op.create_index("ix_permissions_action", ["action"])

    with op.batch_alter_table("role_field_permissions") as batch_op:
        batch_op.add_column(
            sa.Column("access_level", sa.Integer(), nullable=False, server_default=sa.text("1"))
        )
        batch_op.add_column(sa.Column("field_id", postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_role_field_permissions_field_id_fields",
            "fields",
            ["field_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_role_field_permissions_field_id", ["field_id"])

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_position_id_positions",
            "positions",
            ["position_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Заполнить action из code (module.action) — PostgreSQL: split_part
    op.execute(
        """
        UPDATE permissions
        SET action = CASE
            WHEN position('.' in code) > 0 THEN split_part(code, '.', 2)
            ELSE 'view'
        END
        WHERE action = 'view' OR action IS NULL
        """
    )

    # access_level из can_view/can_edit
    op.execute(
        """
        UPDATE role_field_permissions
        SET access_level = CASE
            WHEN can_edit IS TRUE THEN 2
            WHEN can_view IS TRUE THEN 1
            ELSE 0
        END
        """
    )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_position_id_positions", type_="foreignkey")
        batch_op.drop_column("position_id")

    with op.batch_alter_table("role_field_permissions") as batch_op:
        batch_op.drop_index("ix_role_field_permissions_field_id")
        batch_op.drop_constraint("fk_role_field_permissions_field_id_fields", type_="foreignkey")
        batch_op.drop_column("field_id")
        batch_op.drop_column("access_level")

    with op.batch_alter_table("permissions") as batch_op:
        batch_op.drop_index("ix_permissions_action")
        batch_op.drop_index("ix_permissions_module_id")
        batch_op.drop_constraint("fk_permissions_module_id_modules", type_="foreignkey")
        batch_op.drop_column("module_id")
        batch_op.drop_column("action")

    op.drop_index("ix_positions_code_unique_active", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_fields_module_id", table_name="fields")
    op.drop_table("fields")
    op.drop_index("ix_modules_sort_order", table_name="modules")
    op.drop_index("ix_modules_code_unique_active", table_name="modules")
    op.drop_table("modules")
