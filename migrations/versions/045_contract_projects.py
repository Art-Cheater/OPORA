"""Связи контрактов с несколькими проектами.

Revision ID: 045_contract_projects
Revises: 044_object_kind_cable_waybill_status
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "045_contract_projects"
down_revision = "044_object_kind_cable_waybill_status"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "contract_projects" in _tables():
        return
    op.create_table(
        "contract_projects",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), nullable=True),
        sa.Column("updated_by", GUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contract_id", GUID(), nullable=False),
        sa.Column("project_id", GUID(), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contract_projects_contract_id", "contract_projects", ["contract_id"])
    op.create_index("ix_contract_projects_project_id", "contract_projects", ["project_id"])
    op.create_index("ix_contract_projects_pair_active", "contract_projects", ["contract_id", "project_id"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"))
    # Legacy primary project remains in contracts.project_id; copy it without removing compatibility.
    dialect = op.get_bind().dialect.name
    new_id = "md5(random()::text || clock_timestamp()::text)::uuid" if dialect == "postgresql" else "lower(hex(randomblob(16)))"
    op.execute(sa.text(f"""
        INSERT INTO contract_projects (id, created_at, updated_at, contract_id, project_id)
        SELECT {new_id}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, id, project_id
        FROM contracts WHERE project_id IS NOT NULL AND deleted_at IS NULL
    """))


def downgrade() -> None:
    if "contract_projects" in _tables():
        op.drop_table("contract_projects")
