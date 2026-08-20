"""Входящие обращения с корпоративной почты.

Revision ID: 029_inquiries
Revises: 028_agreement_site_coords
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "029_inquiries"
down_revision = "028_agreement_site_coords"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("inquiries"):
        op.create_table(
            "inquiries",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("mailbox", sa.String(255), nullable=False),
            sa.Column("imap_uid", sa.Integer(), nullable=False),
            sa.Column("imap_uidvalidity", sa.Integer(), nullable=False),
            sa.Column("message_id", sa.String(500), nullable=True),
            sa.Column("from_name", sa.String(500), nullable=True),
            sa.Column("from_email", sa.String(255), nullable=True),
            sa.Column("to_email", sa.String(1000), nullable=True),
            sa.Column("subject", sa.String(1000), nullable=False, server_default="(без темы)"),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("body_html", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="new"),
            sa.Column("attachment_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("parse_warning", sa.Text(), nullable=True),
            sa.Column("processed_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.UniqueConstraint("mailbox", "imap_uidvalidity", "imap_uid", name="uq_inquiries_imap_uid"),
        )
        op.create_index("ix_inquiries_received_at", "inquiries", ["received_at"])
        op.create_index("ix_inquiries_status", "inquiries", ["status"])
        op.create_index("ix_inquiries_from_email", "inquiries", ["from_email"])
        op.create_index("ix_inquiries_message_id", "inquiries", ["message_id"])
        op.create_index("ix_inquiries_deleted_received", "inquiries", ["deleted_at", "received_at"])

    if not _has_table("inquiry_mailbox_state"):
        op.create_table(
            "inquiry_mailbox_state",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("mailbox", sa.String(255), nullable=False),
            sa.Column("folder", sa.String(100), nullable=False, server_default="INBOX"),
            sa.Column("uidvalidity", sa.Integer(), nullable=True),
            sa.Column("last_uid", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(1000), nullable=True),
            sa.UniqueConstraint("mailbox", "folder", name="uq_inquiry_mailbox_folder"),
        )


def downgrade() -> None:
    if _has_table("inquiry_mailbox_state"):
        op.drop_table("inquiry_mailbox_state")
    if _has_table("inquiries"):
        op.drop_table("inquiries")
