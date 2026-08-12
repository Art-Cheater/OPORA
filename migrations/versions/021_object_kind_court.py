"""Тип объекта (план/суд/тех.прис.) и номер судебного решения.

Revision ID: 021_object_kind_court
Revises: 020_objects_plan_fields
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "021_object_kind_court"
down_revision = "020_objects_plan_fields"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("work_objects", "object_kind"):
        op.add_column(
            "work_objects",
            sa.Column("object_kind", sa.String(length=30), nullable=True),
        )
        op.create_index("ix_work_objects_object_kind", "work_objects", ["object_kind"])
    if not _has_column("work_objects", "court_decision_number"):
        op.add_column(
            "work_objects",
            sa.Column("court_decision_number", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    if _has_column("work_objects", "court_decision_number"):
        op.drop_column("work_objects", "court_decision_number")
    if _has_column("work_objects", "object_kind"):
        op.drop_index("ix_work_objects_object_kind", table_name="work_objects")
        op.drop_column("work_objects", "object_kind")
