"""Поля плана освещения у объектов + инфополя заявок на торги.

Revision ID: 020_objects_plan_fields
Revises: 019_fix_objects_active
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "020_objects_plan_fields"
down_revision = "019_fix_objects_active"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # --- work_objects ---
    cols = [
        ("work_type", sa.Column("work_type", sa.String(length=255), nullable=True)),
        ("work_deadline", sa.Column("work_deadline", sa.String(length=500), nullable=True)),
        ("contract_number", sa.Column("contract_number", sa.String(length=100), nullable=True)),
        ("contract_date", sa.Column("contract_date", sa.Date(), nullable=True)),
        ("contractor_name", sa.Column("contractor_name", sa.String(length=500), nullable=True)),
        ("contract_amount", sa.Column("contract_amount", sa.Numeric(14, 2), nullable=True)),
        ("budget_amount", sa.Column("budget_amount", sa.Numeric(14, 2), nullable=True)),
        ("result_text", sa.Column("result_text", sa.String(length=500), nullable=True)),
        ("source_sheet", sa.Column("source_sheet", sa.String(length=100), nullable=True)),
    ]
    for name, column in cols:
        if not _has_column("work_objects", name):
            op.add_column("work_objects", column)

    op.alter_column(
        "work_objects",
        "address",
        existing_type=sa.String(length=500),
        type_=sa.String(length=1000),
        existing_nullable=True,
    )
    op.alter_column(
        "work_objects",
        "name",
        existing_type=sa.String(length=500),
        type_=sa.String(length=1000),
        existing_nullable=False,
    )

    if not _has_column("tender_applications", "object_id"):
        op.add_column(
            "tender_applications",
            sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_tender_applications_object_id",
            "tender_applications",
            "work_objects",
            ["object_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_tender_applications_object_id",
            "tender_applications",
            ["object_id"],
        )
    if not _has_column("tender_applications", "work_deadline"):
        op.add_column(
            "tender_applications",
            sa.Column("work_deadline", sa.String(length=500), nullable=True),
        )
    if not _has_column("tender_applications", "published_at"):
        op.add_column(
            "tender_applications",
            sa.Column("published_at", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    for name in ("published_at", "work_deadline"):
        if _has_column("tender_applications", name):
            op.drop_column("tender_applications", name)
    if _has_column("tender_applications", "object_id"):
        op.drop_index("ix_tender_applications_object_id", table_name="tender_applications")
        op.drop_constraint(
            "fk_tender_applications_object_id",
            "tender_applications",
            type_="foreignkey",
        )
        op.drop_column("tender_applications", "object_id")

    for name in (
        "source_sheet",
        "result_text",
        "budget_amount",
        "contract_amount",
        "contractor_name",
        "contract_date",
        "contract_number",
        "work_deadline",
        "work_type",
    ):
        if _has_column("work_objects", name):
            op.drop_column("work_objects", name)
