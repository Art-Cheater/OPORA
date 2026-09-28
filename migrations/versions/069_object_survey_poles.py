"""Точки обследования объекта: опоры на карте лота.

Revision ID: 069_object_survey_poles
Revises: 066_pilot_con10_phase_a
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "069_object_survey_poles"
down_revision = "066_pilot_con10_phase_a"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    if "object_survey_poles" in _insp().get_table_names():
        return
    op.create_table(
        "object_survey_poles",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", GUID(), nullable=True),
        sa.Column("updated_by", GUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "object_id",
            GUID(),
            sa.ForeignKey("work_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("pole_type", sa.String(length=20), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("accuracy_m", sa.Numeric(8, 2), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.CheckConstraint("kind IN ('existing', 'planned')", name="ck_object_survey_poles_kind"),
        sa.CheckConstraint(
            "pole_type IN ('concrete', 'metal', 'other')",
            name="ck_object_survey_poles_type",
        ),
        sa.CheckConstraint("source IN ('gps', 'manual')", name="ck_object_survey_poles_source"),
    )
    op.create_index("ix_object_survey_poles_object", "object_survey_poles", ["object_id"])
    op.create_index(
        "ix_object_survey_poles_lat_lng",
        "object_survey_poles",
        ["latitude", "longitude"],
    )
    op.create_index(
        "ix_object_survey_poles_deleted_created",
        "object_survey_poles",
        ["deleted_at", "created_at"],
    )
    op.create_index("ix_object_survey_poles_deleted_at", "object_survey_poles", ["deleted_at"])


def downgrade() -> None:
    if "object_survey_poles" not in _insp().get_table_names():
        return
    op.drop_index("ix_object_survey_poles_deleted_at", table_name="object_survey_poles")
    op.drop_index("ix_object_survey_poles_deleted_created", table_name="object_survey_poles")
    op.drop_index("ix_object_survey_poles_lat_lng", table_name="object_survey_poles")
    op.drop_index("ix_object_survey_poles_object", table_name="object_survey_poles")
    op.drop_table("object_survey_poles")
