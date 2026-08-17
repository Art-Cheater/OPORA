"""Объёмы проекта (СИП/опоры/светильники/ШУНО) и дата срока заявки на торги.

Revision ID: 025_project_volumes_tender_deadline
Revises: 024_list_deleted_created_indexes
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "025_project_volumes_tender_deadline"
down_revision = "024_list_deleted_created_indexes"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    project_cols = [
        ("sip_meters", sa.Column("sip_meters", sa.Numeric(12, 2), nullable=True)),
        ("poles_count", sa.Column("poles_count", sa.Integer(), nullable=True)),
        ("lights_count", sa.Column("lights_count", sa.Integer(), nullable=True)),
        ("shuno_count", sa.Column("shuno_count", sa.Integer(), nullable=True)),
        ("sip_meters_fact", sa.Column("sip_meters_fact", sa.Numeric(12, 2), nullable=True)),
        ("poles_count_fact", sa.Column("poles_count_fact", sa.Integer(), nullable=True)),
        ("lights_count_fact", sa.Column("lights_count_fact", sa.Integer(), nullable=True)),
        ("shuno_count_fact", sa.Column("shuno_count_fact", sa.Integer(), nullable=True)),
    ]
    for name, column in project_cols:
        if not _has_column("projects", name):
            op.add_column("projects", column)

    if not _has_column("tender_applications", "work_deadline_date"):
        op.add_column(
            "tender_applications",
            sa.Column("work_deadline_date", sa.Date(), nullable=True),
        )
        op.create_index(
            "ix_tender_applications_work_deadline_date",
            "tender_applications",
            ["work_deadline_date"],
        )


def downgrade() -> None:
    if _has_column("tender_applications", "work_deadline_date"):
        op.drop_index(
            "ix_tender_applications_work_deadline_date",
            table_name="tender_applications",
        )
        op.drop_column("tender_applications", "work_deadline_date")
    for name in (
        "shuno_count_fact",
        "lights_count_fact",
        "poles_count_fact",
        "sip_meters_fact",
        "shuno_count",
        "lights_count",
        "poles_count",
        "sip_meters",
    ):
        if _has_column("projects", name):
            op.drop_column("projects", name)
