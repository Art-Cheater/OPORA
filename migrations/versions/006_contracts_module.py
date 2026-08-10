"""Расширение схемы для CRM-модуля контрактов.

Revision ID: 006_contracts_module
Revises: 005_projects_module
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "006_contracts_module"
down_revision = "005_projects_module"
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
        "contracts",
        sa.Column("contract_type", sa.String(length=30), nullable=False, server_default="other"),
    )
    op.add_column("contracts", sa.Column("contract_date", sa.Date(), nullable=True))
    op.add_column("contracts", sa.Column("responsible_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.create_foreign_key(
        "fk_contracts_responsible_id_users",
        "contracts",
        "users",
        ["responsible_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_contracts_contract_type", "contracts", ["contract_type"], unique=False)
    op.create_index("ix_contracts_responsible_id", "contracts", ["responsible_id"], unique=False)
    op.create_index("ix_contracts_contract_date", "contracts", ["contract_date"], unique=False)

    op.create_table(
        "contract_history",
        *AUDIT_COLUMNS,
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False, server_default="update"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_contract_history_created_at", "contract_history", ["created_at"])
    op.create_index("ix_contract_history_deleted_at", "contract_history", ["deleted_at"])
    op.create_index("ix_contract_history_contract_id", "contract_history", ["contract_id"])
    op.create_index("ix_contract_history_changed_by", "contract_history", ["changed_by"])

    op.create_table(
        "contract_documents",
        *AUDIT_COLUMNS,
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("document_number", sa.String(length=100), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=True),
        sa.Column("storage_key", sa.String(length=1000), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_contract_documents_created_at", "contract_documents", ["created_at"])
    op.create_index("ix_contract_documents_deleted_at", "contract_documents", ["deleted_at"])
    op.create_index("ix_contract_documents_contract_id", "contract_documents", ["contract_id"])


def downgrade():
    op.drop_index("ix_contract_documents_contract_id", table_name="contract_documents")
    op.drop_index("ix_contract_documents_deleted_at", table_name="contract_documents")
    op.drop_index("ix_contract_documents_created_at", table_name="contract_documents")
    op.drop_table("contract_documents")

    op.drop_index("ix_contract_history_changed_by", table_name="contract_history")
    op.drop_index("ix_contract_history_contract_id", table_name="contract_history")
    op.drop_index("ix_contract_history_deleted_at", table_name="contract_history")
    op.drop_index("ix_contract_history_created_at", table_name="contract_history")
    op.drop_table("contract_history")

    op.drop_index("ix_contracts_contract_date", table_name="contracts")
    op.drop_index("ix_contracts_responsible_id", table_name="contracts")
    op.drop_index("ix_contracts_contract_type", table_name="contracts")
    op.drop_constraint("fk_contracts_responsible_id_users", "contracts", type_="foreignkey")
    op.drop_column("contracts", "responsible_id")
    op.drop_column("contracts", "contract_date")
    op.drop_column("contracts", "contract_type")
