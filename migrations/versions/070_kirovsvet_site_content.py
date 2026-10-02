"""Кабинет сайта Кировсвет: телефоны, график, новости.

Revision ID: 070_kirovsvet_site_content
Revises: 068_work_order_blanks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "070_kirovsvet_site_content"
down_revision = "068_work_order_blanks"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    names = set(_insp().get_table_names())
    if "kirovsvet_contacts" not in names:
        op.create_table(
            "kirovsvet_contacts",
            sa.Column("key", sa.String(length=32), primary_key=True),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("note", sa.String(length=300), nullable=False, server_default=""),
            sa.Column("phone", sa.String(length=40), nullable=False),
            sa.Column("hours", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        op.bulk_insert(
            sa.table(
                "kirovsvet_contacts",
                sa.column("key", sa.String),
                sa.column("title", sa.String),
                sa.column("note", sa.String),
                sa.column("phone", sa.String),
                sa.column("hours", sa.String),
                sa.column("sort_order", sa.Integer),
            ),
            [
                {"key": "dispatcher", "title": "Диспетчерская", "note": "Заявки и аварии", "phone": "+7 (8332) 00-00-01", "hours": "Круглосуточно", "sort_order": 10},
                {"key": "reception", "title": "Приёмная", "note": "Письма, обращения, документы", "phone": "+7 (8332) 00-00-02", "hours": "Пн–чт 8:00–17:00, пт 8:00–16:00", "sort_order": 20},
                {"key": "tech", "title": "Технический отдел", "note": "Подрядчики, согласования, работы рядом с сетями", "phone": "+7 (8332) 00-00-03", "hours": "Пн–пт 9:00–16:00", "sort_order": 30},
                {"key": "edds", "title": "ЕДДС города Кирова", "note": "Запасной номер, если диспетчер занят", "phone": "76-00-00", "hours": "Круглосуточно", "sort_order": 40},
            ],
        )
    if "kirovsvet_schedule" not in names:
        op.create_table(
            "kirovsvet_schedule",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("on_after_sunset", sa.Integer(), nullable=False, server_default="15"),
            sa.Column("off_before_sunrise", sa.Integer(), nullable=False, server_default="15"),
        )
        op.bulk_insert(
            sa.table(
                "kirovsvet_schedule",
                sa.column("id", sa.Integer),
                sa.column("on_after_sunset", sa.Integer),
                sa.column("off_before_sunrise", sa.Integer),
            ),
            [{"id": 1, "on_after_sunset": 15, "off_before_sunrise": 15}],
        )
    if "kirovsvet_schedule_days" not in names:
        op.create_table(
            "kirovsvet_schedule_days",
            sa.Column("day", sa.Date(), primary_key=True),
            sa.Column("on_time", sa.String(length=5), nullable=False),
            sa.Column("off_time", sa.String(length=5), nullable=False),
        )
    if "kirovsvet_news" not in names:
        op.create_table(
            "kirovsvet_news",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("lead", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("image_name", sa.String(length=80), nullable=True),
            sa.Column("published_on", sa.Date(), nullable=False),
            sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_kirovsvet_news_slug", "kirovsvet_news", ["slug"], unique=True)
        op.create_index("ix_kirovsvet_news_published", "kirovsvet_news", ["is_published", "published_on"])


def downgrade() -> None:
    names = set(_insp().get_table_names())
    if "kirovsvet_news" in names:
        op.drop_index("ix_kirovsvet_news_published", table_name="kirovsvet_news")
        op.drop_index("ix_kirovsvet_news_slug", table_name="kirovsvet_news")
        op.drop_table("kirovsvet_news")
    if "kirovsvet_schedule_days" in names:
        op.drop_table("kirovsvet_schedule_days")
    if "kirovsvet_schedule" in names:
        op.drop_table("kirovsvet_schedule")
    if "kirovsvet_contacts" in names:
        op.drop_table("kirovsvet_contacts")
