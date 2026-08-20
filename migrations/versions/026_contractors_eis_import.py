"""Подрядчики, номера ЕИС, НМЦК заявок, журнал импорта.

Revision ID: 026_contractors_eis_import
Revises: 025_project_volumes_tender_deadline
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "026_contractors_eis_import"
down_revision = "025_project_volumes_tender_deadline"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("contractors"):
        op.create_table(
            "contractors",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column("inn", sa.String(12), nullable=True),
            sa.Column("kpp", sa.String(9), nullable=True),
            sa.Column("kpp_largest", sa.String(9), nullable=True),
            sa.Column("address", sa.String(1000), nullable=True),
            sa.Column("phone", sa.String(50), nullable=True),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_contractors_name", "contractors", ["name"])
        op.create_index(
            "ix_contractors_deleted_created", "contractors", ["deleted_at", "created_at"]
        )

    if not _has_table("contract_contractors"):
        op.create_table(
            "contract_contractors",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "contract_id",
                GUID(),
                sa.ForeignKey("contracts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "contractor_id",
                GUID(),
                sa.ForeignKey("contractors.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.UniqueConstraint("contract_id", "contractor_id", name="uq_contract_contractors_pair"),
        )
        op.create_index(
            "ix_contract_contractors_contract_id", "contract_contractors", ["contract_id"]
        )
        op.create_index(
            "ix_contract_contractors_contractor_id",
            "contract_contractors",
            ["contractor_id"],
        )

    if not _has_table("eis_import_runs"):
        op.create_table(
            "eis_import_runs",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(20), nullable=False, server_default="running"),
            sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("summary", JSONType(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_eis_import_runs_started_at", "eis_import_runs", ["started_at"])
        op.create_index("ix_eis_import_runs_status", "eis_import_runs", ["status"])
        op.create_index("ix_eis_import_runs_user_id", "eis_import_runs", ["user_id"])

    if not _has_table("eis_import_events"):
        op.create_table(
            "eis_import_events",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "run_id",
                GUID(),
                sa.ForeignKey("eis_import_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=True),
            sa.Column("entity_id", GUID(), nullable=True),
            sa.Column("eis_number", sa.String(64), nullable=True),
            sa.Column("url", sa.String(700), nullable=True),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("extra", JSONType(), nullable=True),
        )
        op.create_index("ix_eis_import_events_run_id", "eis_import_events", ["run_id"])
        op.create_index("ix_eis_import_events_kind", "eis_import_events", ["kind"])
        op.create_index("ix_eis_import_events_eis_number", "eis_import_events", ["eis_number"])

    for name, column in (
        ("eis_reestr_number", sa.Column("eis_reestr_number", sa.String(32), nullable=True)),
        ("eis_stage", sa.Column("eis_stage", sa.String(200), nullable=True)),
        ("eis_url", sa.Column("eis_url", sa.String(700), nullable=True)),
        ("delivery_place", sa.Column("delivery_place", sa.Text(), nullable=True)),
    ):
        if not _has_column("contracts", name):
            op.add_column("contracts", column)

    for name, column in (
        ("nmck", sa.Column("nmck", sa.Numeric(18, 2), nullable=True)),
        ("eis_reg_number", sa.Column("eis_reg_number", sa.String(32), nullable=True)),
        ("eis_status", sa.Column("eis_status", sa.String(200), nullable=True)),
        ("eis_url", sa.Column("eis_url", sa.String(700), nullable=True)),
    ):
        if not _has_column("tender_applications", name):
            op.add_column("tender_applications", column)


def downgrade() -> None:
    if _has_table("eis_import_events"):
        op.drop_table("eis_import_events")
    if _has_table("eis_import_runs"):
        op.drop_table("eis_import_runs")
    if _has_table("contract_contractors"):
        op.drop_table("contract_contractors")
    if _has_table("contractors"):
        op.drop_table("contractors")
    for name in ("eis_url", "eis_status", "eis_reg_number", "nmck"):
        if _has_column("tender_applications", name):
            op.drop_column("tender_applications", name)
    for name in ("delivery_place", "eis_url", "eis_stage", "eis_reestr_number"):
        if _has_column("contracts", name):
            op.drop_column("contracts", name)
