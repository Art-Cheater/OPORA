"""Сохранённые бланки-распоряжения.

Revision ID: 068_work_order_blanks
Revises: 069_object_survey_poles
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "068_work_order_blanks"
down_revision = "069_object_survey_poles"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    if "work_order_blanks" in _insp().get_table_names():
        return
    op.create_table(
        "work_order_blanks",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), nullable=True),
        sa.Column("updated_by", GUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_id", GUID(), sa.ForeignKey("work_plans.id", ondelete="CASCADE"), nullable=True),
        sa.Column("request_id", GUID(), sa.ForeignKey("requests.id", ondelete="CASCADE"), nullable=True),
        sa.Column("order_number", sa.String(length=100), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("producer", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("crew_count", sa.String(length=20), nullable=True),
        sa.Column("crew_lead", sa.String(length=255), nullable=True),
        sa.Column("crew_members", sa.String(length=500), nullable=True),
        sa.Column("lift_responsible", sa.String(length=255), nullable=True),
        sa.Column("issuer", sa.String(length=255), nullable=True),
        sa.Column("briefing_conductor", sa.String(length=255), nullable=True),
        sa.Column("needs_update", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("closed_by_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_work_order_blanks_deleted_at", "work_order_blanks", ["deleted_at"])
    op.create_index("ix_work_order_blanks_plan_id", "work_order_blanks", ["plan_id"])
    op.create_index("ix_work_order_blanks_request_id", "work_order_blanks", ["request_id"])
    op.create_index("ix_work_order_blanks_closed_by_id", "work_order_blanks", ["closed_by_id"])
    op.create_index(
        "uq_work_order_blanks_plan",
        "work_order_blanks",
        ["plan_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND plan_id IS NOT NULL"),
        sqlite_where=sa.text("deleted_at IS NULL AND plan_id IS NOT NULL"),
    )
    op.create_index(
        "uq_work_order_blanks_request",
        "work_order_blanks",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND plan_id IS NULL AND request_id IS NOT NULL"),
        sqlite_where=sa.text("deleted_at IS NULL AND plan_id IS NULL AND request_id IS NOT NULL"),
    )


def downgrade() -> None:
    if "work_order_blanks" not in _insp().get_table_names():
        return
    op.drop_index("uq_work_order_blanks_request", table_name="work_order_blanks")
    op.drop_index("uq_work_order_blanks_plan", table_name="work_order_blanks")
    op.drop_index("ix_work_order_blanks_closed_by_id", table_name="work_order_blanks")
    op.drop_index("ix_work_order_blanks_request_id", table_name="work_order_blanks")
    op.drop_index("ix_work_order_blanks_plan_id", table_name="work_order_blanks")
    op.drop_index("ix_work_order_blanks_deleted_at", table_name="work_order_blanks")
    op.drop_table("work_order_blanks")
