"""Миграция: объекты, заявки на торги, связи с проектами и контрактами.

Revision ID: 018_procurement_chain
Revises: 017_request_barrier_repeats
Create Date: 2026-08-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "018_procurement_chain"
down_revision = "017_request_barrier_repeats"
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
        "work_objects",
        *AUDIT_COLUMNS,
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("plan_year", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_work_objects_created_at", "work_objects", ["created_at"])
    op.create_index("ix_work_objects_deleted_at", "work_objects", ["deleted_at"])
    op.create_index("ix_work_objects_is_active", "work_objects", ["is_active"])
    op.create_index("ix_work_objects_status", "work_objects", ["status"])
    op.create_index("ix_work_objects_plan_year", "work_objects", ["plan_year"])
    op.create_index("ix_work_objects_name", "work_objects", ["name"])

    op.create_table(
        "tender_applications",
        *AUDIT_COLUMNS,
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("responsible_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["responsible_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tender_applications_created_at", "tender_applications", ["created_at"])
    op.create_index("ix_tender_applications_deleted_at", "tender_applications", ["deleted_at"])
    op.create_index("ix_tender_applications_is_active", "tender_applications", ["is_active"])
    op.create_index("ix_tender_applications_status", "tender_applications", ["status"])
    op.create_index("ix_tender_applications_responsible_id", "tender_applications", ["responsible_id"])
    op.create_index(
        "ix_tender_applications_number_unique_active",
        "tender_applications",
        ["number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "tender_projects",
        *AUDIT_COLUMNS,
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["tender_id"], ["tender_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tender_id", "project_id", name="uq_tender_projects_tender_project"),
    )
    op.create_index("ix_tender_projects_created_at", "tender_projects", ["created_at"])
    op.create_index("ix_tender_projects_deleted_at", "tender_projects", ["deleted_at"])
    op.create_index("ix_tender_projects_tender_id", "tender_projects", ["tender_id"])
    op.create_index("ix_tender_projects_project_id", "tender_projects", ["project_id"])

    op.create_table(
        "tender_documents",
        *AUDIT_COLUMNS,
        sa.Column("tender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("document_number", sa.String(length=100), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=True),
        sa.Column("storage_key", sa.String(length=1000), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["tender_id"], ["tender_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tender_documents_created_at", "tender_documents", ["created_at"])
    op.create_index("ix_tender_documents_deleted_at", "tender_documents", ["deleted_at"])
    op.create_index("ix_tender_documents_tender_id", "tender_documents", ["tender_id"])
    op.create_index("ix_tender_documents_document_type", "tender_documents", ["document_type"])

    op.add_column("projects", sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_projects_object_id_work_objects",
        "projects",
        "work_objects",
        ["object_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_projects_object_id", "projects", ["object_id"])

    op.add_column(
        "contracts",
        sa.Column("tender_application_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_contracts_tender_application_id",
        "contracts",
        "tender_applications",
        ["tender_application_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_contracts_tender_application_id", "contracts", ["tender_application_id"])

    op.add_column(
        "contract_documents",
        sa.Column("document_type", sa.String(length=30), nullable=False, server_default="other"),
    )
    op.create_index("ix_contract_documents_document_type", "contract_documents", ["document_type"])

    op.create_table(
        "contract_objects",
        *AUDIT_COLUMNS,
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["object_id"], ["work_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("contract_id", "object_id", name="uq_contract_objects_contract_object"),
    )
    op.create_index("ix_contract_objects_created_at", "contract_objects", ["created_at"])
    op.create_index("ix_contract_objects_deleted_at", "contract_objects", ["deleted_at"])
    op.create_index("ix_contract_objects_contract_id", "contract_objects", ["contract_id"])
    op.create_index("ix_contract_objects_object_id", "contract_objects", ["object_id"])


def downgrade():
    op.drop_index("ix_contract_objects_object_id", table_name="contract_objects")
    op.drop_index("ix_contract_objects_contract_id", table_name="contract_objects")
    op.drop_index("ix_contract_objects_deleted_at", table_name="contract_objects")
    op.drop_index("ix_contract_objects_created_at", table_name="contract_objects")
    op.drop_table("contract_objects")

    op.drop_index("ix_contract_documents_document_type", table_name="contract_documents")
    op.drop_column("contract_documents", "document_type")

    op.drop_index("ix_contracts_tender_application_id", table_name="contracts")
    op.drop_constraint("fk_contracts_tender_application_id", "contracts", type_="foreignkey")
    op.drop_column("contracts", "tender_application_id")

    op.drop_index("ix_projects_object_id", table_name="projects")
    op.drop_constraint("fk_projects_object_id_work_objects", "projects", type_="foreignkey")
    op.drop_column("projects", "object_id")

    op.drop_index("ix_tender_documents_document_type", table_name="tender_documents")
    op.drop_index("ix_tender_documents_tender_id", table_name="tender_documents")
    op.drop_index("ix_tender_documents_deleted_at", table_name="tender_documents")
    op.drop_index("ix_tender_documents_created_at", table_name="tender_documents")
    op.drop_table("tender_documents")

    op.drop_index("ix_tender_projects_project_id", table_name="tender_projects")
    op.drop_index("ix_tender_projects_tender_id", table_name="tender_projects")
    op.drop_index("ix_tender_projects_deleted_at", table_name="tender_projects")
    op.drop_index("ix_tender_projects_created_at", table_name="tender_projects")
    op.drop_table("tender_projects")

    op.drop_index("ix_tender_applications_number_unique_active", table_name="tender_applications")
    op.drop_index("ix_tender_applications_responsible_id", table_name="tender_applications")
    op.drop_index("ix_tender_applications_status", table_name="tender_applications")
    op.drop_index("ix_tender_applications_is_active", table_name="tender_applications")
    op.drop_index("ix_tender_applications_deleted_at", table_name="tender_applications")
    op.drop_index("ix_tender_applications_created_at", table_name="tender_applications")
    op.drop_table("tender_applications")

    op.drop_index("ix_work_objects_name", table_name="work_objects")
    op.drop_index("ix_work_objects_plan_year", table_name="work_objects")
    op.drop_index("ix_work_objects_status", table_name="work_objects")
    op.drop_index("ix_work_objects_is_active", table_name="work_objects")
    op.drop_index("ix_work_objects_deleted_at", table_name="work_objects")
    op.drop_index("ix_work_objects_created_at", table_name="work_objects")
    op.drop_table("work_objects")
