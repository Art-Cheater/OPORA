"""Тип объекта «Другое», кабель в проекте, предыдущий статус точки путевого листа.

Revision ID: 044_object_kind_cable_waybill_status
Revises: 043_work_plans
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "044_object_kind_cable_waybill_status"
down_revision = "043_work_plans"
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


def upgrade() -> None:
    if _has_table("work_objects") and not _has_column("work_objects", "kind_comment"):
        op.add_column(
            "work_objects",
            sa.Column("kind_comment", sa.String(length=500), nullable=True),
        )
    for name in ("cable_meters", "cable_meters_fact"):
        if _has_table("projects") and not _has_column("projects", name):
            op.add_column(
                "projects",
                sa.Column(name, sa.Numeric(12, 2), nullable=True),
            )
    if _has_table("waybill_stops") and not _has_column("waybill_stops", "previous_status_code"):
        op.add_column(
            "waybill_stops",
            sa.Column("previous_status_code", sa.String(length=50), nullable=True),
        )


def downgrade() -> None:
    if _has_column("waybill_stops", "previous_status_code"):
        op.drop_column("waybill_stops", "previous_status_code")
    for name in ("cable_meters_fact", "cable_meters"):
        if _has_column("projects", name):
            op.drop_column("projects", name)
    if _has_column("work_objects", "kind_comment"):
        op.drop_column("work_objects", "kind_comment")
