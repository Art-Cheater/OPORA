"""Расширение схемы для CRM-модуля заявок.

Revision ID: 004_requests_module
Revises: 003_security
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004_requests_module"
down_revision = "003_security"
branch_labels = None
depends_on = None


def upgrade():
    # requests
    op.add_column("requests", sa.Column("address", sa.String(length=500), nullable=False, server_default=""))
    op.add_column("requests", sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=True))
    op.add_column("requests", sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=True))
    op.add_column("requests", sa.Column("phone", sa.String(length=30), nullable=True))
    op.add_column("requests", sa.Column("applicant_name", sa.String(length=255), nullable=False, server_default="Не указан"))
    op.add_column("requests", sa.Column("responsible_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("requests", sa.Column("executor_id", postgresql.UUID(as_uuid=True), nullable=True))

    op.create_foreign_key(
        "fk_requests_responsible_id_users",
        "requests",
        "users",
        ["responsible_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_requests_executor_id_users",
        "requests",
        "users",
        ["executor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_requests_address", "requests", ["address"], unique=False)
    op.create_index("ix_requests_responsible_id", "requests", ["responsible_id"], unique=False)
    op.create_index("ix_requests_executor_id", "requests", ["executor_id"], unique=False)

    # old assignee -> responsible
    op.execute(sa.text("UPDATE requests SET responsible_id = assignee_id WHERE assignee_id IS NOT NULL"))

    # request_history
    op.add_column("request_history", sa.Column("action", sa.String(length=50), nullable=False, server_default="update"))
    op.add_column("request_history", sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # request_materials
    op.create_table(
        "request_materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_request_materials_created_by_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_request_materials_updated_by_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_request_materials_deleted_at", "request_materials", ["deleted_at"], unique=False)
    op.create_index("ix_request_materials_request_id", "request_materials", ["request_id"], unique=False)
    op.create_index("ix_request_materials_name", "request_materials", ["name"], unique=False)

    # drop server defaults after backfill
    op.alter_column("requests", "address", server_default=None)
    op.alter_column("requests", "applicant_name", server_default=None)
    op.alter_column("request_history", "action", server_default=None)


def downgrade():
    op.drop_index("ix_request_materials_name", table_name="request_materials")
    op.drop_index("ix_request_materials_request_id", table_name="request_materials")
    op.drop_index("ix_request_materials_deleted_at", table_name="request_materials")
    op.drop_table("request_materials")

    op.drop_column("request_history", "details")
    op.drop_column("request_history", "action")

    op.drop_index("ix_requests_executor_id", table_name="requests")
    op.drop_index("ix_requests_responsible_id", table_name="requests")
    op.drop_index("ix_requests_address", table_name="requests")
    op.drop_constraint("fk_requests_executor_id_users", "requests", type_="foreignkey")
    op.drop_constraint("fk_requests_responsible_id_users", "requests", type_="foreignkey")
    op.drop_column("requests", "executor_id")
    op.drop_column("requests", "responsible_id")
    op.drop_column("requests", "applicant_name")
    op.drop_column("requests", "phone")
    op.drop_column("requests", "longitude")
    op.drop_column("requests", "latitude")
    op.drop_column("requests", "address")
