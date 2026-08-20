"""Пересылка обращений сотрудникам и карточки в чате.

Revision ID: 030_inquiry_forward
Revises: 029_inquiries
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "030_inquiry_forward"
down_revision = "029_inquiries"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return name in {idx["name"] for idx in insp.get_indexes(table)}


def upgrade() -> None:
    if not _has_column("inquiries", "assigned_to"):
        op.add_column("inquiries", sa.Column("assigned_to", GUID(), nullable=True))
        op.create_foreign_key(
            "fk_inquiries_assigned_to_users",
            "inquiries",
            "users",
            ["assigned_to"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_column("inquiries", "forwarded_by"):
        op.add_column("inquiries", sa.Column("forwarded_by", GUID(), nullable=True))
        op.create_foreign_key(
            "fk_inquiries_forwarded_by_users",
            "inquiries",
            "users",
            ["forwarded_by"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_column("inquiries", "forwarded_at"):
        op.add_column(
            "inquiries",
            sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_index("inquiries", "ix_inquiries_assigned_to"):
        op.create_index("ix_inquiries_assigned_to", "inquiries", ["assigned_to"])
    if not _has_index("inquiries", "ix_inquiries_forwarded_by"):
        op.create_index("ix_inquiries_forwarded_by", "inquiries", ["forwarded_by"])

    if not _has_column("messenger_messages", "card_type"):
        op.add_column("messenger_messages", sa.Column("card_type", sa.String(20), nullable=True))
    if not _has_column("messenger_messages", "card_id"):
        op.add_column("messenger_messages", sa.Column("card_id", GUID(), nullable=True))
    if not _has_column("messenger_messages", "card_title"):
        op.add_column("messenger_messages", sa.Column("card_title", sa.String(500), nullable=True))
    if not _has_column("messenger_messages", "card_subtitle"):
        op.add_column("messenger_messages", sa.Column("card_subtitle", sa.String(500), nullable=True))
    if not _has_column("messenger_messages", "card_url"):
        op.add_column("messenger_messages", sa.Column("card_url", sa.String(700), nullable=True))


def downgrade() -> None:
    if _has_column("messenger_messages", "card_url"):
        op.drop_column("messenger_messages", "card_url")
    if _has_column("messenger_messages", "card_subtitle"):
        op.drop_column("messenger_messages", "card_subtitle")
    if _has_column("messenger_messages", "card_title"):
        op.drop_column("messenger_messages", "card_title")
    if _has_column("messenger_messages", "card_id"):
        op.drop_column("messenger_messages", "card_id")
    if _has_column("messenger_messages", "card_type"):
        op.drop_column("messenger_messages", "card_type")

    if _has_index("inquiries", "ix_inquiries_forwarded_by"):
        op.drop_index("ix_inquiries_forwarded_by", table_name="inquiries")
    if _has_index("inquiries", "ix_inquiries_assigned_to"):
        op.drop_index("ix_inquiries_assigned_to", table_name="inquiries")
    if _has_column("inquiries", "forwarded_at"):
        op.drop_column("inquiries", "forwarded_at")
    if _has_column("inquiries", "forwarded_by"):
        op.drop_constraint("fk_inquiries_forwarded_by_users", "inquiries", type_="foreignkey")
        op.drop_column("inquiries", "forwarded_by")
    if _has_column("inquiries", "assigned_to"):
        op.drop_constraint("fk_inquiries_assigned_to_users", "inquiries", type_="foreignkey")
        op.drop_column("inquiries", "assigned_to")
