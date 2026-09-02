"""Планы работ мастера и пункт питания у дефектов.

Revision ID: 043_work_plans
Revises: 042_drop_request_defects
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "043_work_plans"
down_revision = "042_drop_request_defects"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _insp().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {col["name"] for col in _insp().get_columns(table)}


def _base_columns():
    return [
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    if _has_table("defects") and not _has_column("defects", "pp"):
        op.add_column("defects", sa.Column("pp", sa.String(length=255), nullable=True))
        op.create_index("ix_defects_pp", "defects", ["pp"])

    if not _has_table("work_plans"):
        op.create_table(
            "work_plans",
            *_base_columns(),
            sa.Column("number", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("master_id", GUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_work_plans_deleted_at", "work_plans", ["deleted_at"])
        op.create_index("ix_work_plans_number", "work_plans", ["number"], unique=True)
        op.create_index("ix_work_plans_master_id", "work_plans", ["master_id"])
        op.create_index("ix_work_plans_status", "work_plans", ["status"])
        op.create_index("ix_work_plans_deleted_created", "work_plans", ["deleted_at", "created_at"])
        op.create_index(
            "uq_work_plans_master_draft",
            "work_plans",
            ["master_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL AND status = 'draft'"),
            sqlite_where=sa.text("deleted_at IS NULL AND status = 'draft'"),
        )

    if not _has_table("work_plan_items"):
        op.create_table(
            "work_plan_items",
            *_base_columns(),
            sa.Column("plan_id", GUID(), sa.ForeignKey("work_plans.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("request_id", GUID(), sa.ForeignKey("requests.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("defect_id", GUID(), sa.ForeignKey("defects.id", ondelete="RESTRICT"), nullable=True),
            sa.Column("result", sa.String(length=30), nullable=False, server_default="active"),
            sa.Column("number_snapshot", sa.String(length=50), nullable=False, server_default=""),
            sa.Column("address_snapshot", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("pp_snapshot", sa.String(length=255), nullable=True),
            sa.Column("description_snapshot", sa.Text(), nullable=True),
            sa.Column("street_snapshot", sa.String(length=500), nullable=True),
            sa.Column("district_snapshot", sa.String(length=255), nullable=True),
            sa.Column("previous_status_code", sa.String(length=50), nullable=True),
            sa.Column("complete_comment", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("exclude_reason", sa.String(length=50), nullable=True),
            sa.Column("exclude_comment", sa.Text(), nullable=True),
            sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("excluded_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.CheckConstraint(
                "(request_id IS NOT NULL AND defect_id IS NULL) "
                "OR (request_id IS NULL AND defect_id IS NOT NULL)",
                name="ck_work_plan_items_one_target",
            ),
        )
        op.create_index("ix_work_plan_items_deleted_at", "work_plan_items", ["deleted_at"])
        op.create_index("ix_work_plan_items_plan_id", "work_plan_items", ["plan_id"])
        op.create_index("ix_work_plan_items_request_id", "work_plan_items", ["request_id"])
        op.create_index("ix_work_plan_items_defect_id", "work_plan_items", ["defect_id"])
        op.create_index("ix_work_plan_items_result", "work_plan_items", ["result"])
        op.create_index(
            "uq_work_plan_items_request",
            "work_plan_items",
            ["plan_id", "request_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL AND request_id IS NOT NULL"),
            sqlite_where=sa.text("deleted_at IS NULL AND request_id IS NOT NULL"),
        )
        op.create_index(
            "uq_work_plan_items_defect",
            "work_plan_items",
            ["plan_id", "defect_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL AND defect_id IS NOT NULL"),
            sqlite_where=sa.text("deleted_at IS NULL AND defect_id IS NOT NULL"),
        )

    if not _has_table("work_plan_history"):
        op.create_table(
            "work_plan_history",
            *_base_columns(),
            sa.Column("plan_id", GUID(), sa.ForeignKey("work_plans.id", ondelete="CASCADE"), nullable=False),
            sa.Column("item_id", GUID(), sa.ForeignKey("work_plan_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=50), nullable=False, server_default="update"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("details", JSONType(), nullable=True),
            sa.Column("changed_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_work_plan_history_deleted_at", "work_plan_history", ["deleted_at"])
        op.create_index("ix_work_plan_history_plan_id", "work_plan_history", ["plan_id"])
        op.create_index("ix_work_plan_history_item_id", "work_plan_history", ["item_id"])
        op.create_index("ix_work_plan_history_changed_by", "work_plan_history", ["changed_by"])


def downgrade() -> None:
    if _has_table("work_plan_history"):
        op.drop_table("work_plan_history")
    if _has_table("work_plan_items"):
        op.drop_table("work_plan_items")
    if _has_table("work_plans"):
        op.drop_table("work_plans")
    if _has_table("defects") and _has_column("defects", "pp"):
        op.drop_index("ix_defects_pp", table_name="defects")
        op.drop_column("defects", "pp")
