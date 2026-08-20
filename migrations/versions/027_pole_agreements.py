"""Договора на размещение оборудования на опорах НО.

Revision ID: 027_pole_agreements
Revises: 026_contractors_eis_import
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONType

revision = "027_pole_agreements"
down_revision = "026_contractors_eis_import"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("pole_agreements"):
        op.create_table(
            "pole_agreements",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("number", sa.String(100), nullable=True),
            sa.Column("subject", sa.String(1000), nullable=True),
            sa.Column("customer_name", sa.String(500), nullable=True),
            sa.Column("customer_inn", sa.String(12), nullable=True),
            sa.Column("period_from", sa.Date(), nullable=True),
            sa.Column("period_to", sa.Date(), nullable=True),
            sa.Column("source_filename", sa.String(500), nullable=True),
            sa.Column("storage_key", sa.String(700), nullable=True),
            sa.Column("mime_type", sa.String(150), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("parse_warning", sa.Text(), nullable=True),
            sa.Column("uploaded_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_pole_agreements_customer_name", "pole_agreements", ["customer_name"])
        op.create_index(
            "ix_pole_agreements_deleted_created", "pole_agreements", ["deleted_at", "created_at"]
        )

    if not _has_table("pole_agreement_sites"):
        op.create_table(
            "pole_agreement_sites",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "agreement_id",
                GUID(),
                sa.ForeignKey("pole_agreements.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("row_no", sa.String(30), nullable=True),
            sa.Column("address", sa.String(2000), nullable=False),
            sa.Column("address_norm", sa.String(2000), nullable=True),
            sa.Column("mounts_count", sa.Integer(), nullable=True),
            sa.Column("poles_count", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("extra", JSONType(), nullable=True),
        )
        op.create_index("ix_pole_agreement_sites_agreement_id", "pole_agreement_sites", ["agreement_id"])
        op.create_index("ix_pole_agreement_sites_address_norm", "pole_agreement_sites", ["address_norm"])


def downgrade() -> None:
    if _has_table("pole_agreement_sites"):
        op.drop_table("pole_agreement_sites")
    if _has_table("pole_agreements"):
        op.drop_table("pole_agreements")
