"""Обои интерфейса — миграция каталога.

Revision ID: 037_wallpapers
Revises: 036_user_ui_preferences
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID

revision = "037_wallpapers"
down_revision = "036_user_ui_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "wallpapers" not in insp.get_table_names():
        op.create_table(
            "wallpapers",
            sa.Column("id", GUID(), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_by", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("storage_key", sa.String(length=500), nullable=False),
            sa.Column("mime_type", sa.String(length=100), nullable=False, server_default="image/jpeg"),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index("ix_wallpapers_deleted_at", "wallpapers", ["deleted_at"])
        op.create_index("ix_wallpapers_sort_order", "wallpapers", ["sort_order"])

    # Сброс старых hardcoded id (kirov_*, corporate) → none
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "ui_background" in cols:
            op.execute(
                sa.text(
                    "UPDATE users SET ui_background = 'none' "
                    "WHERE ui_background IS NOT NULL "
                    "AND ui_background NOT IN ('none', 'custom') "
                    "AND ui_background NOT LIKE 'wp:%'"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "wallpapers" in insp.get_table_names():
        op.drop_index("ix_wallpapers_sort_order", table_name="wallpapers")
        op.drop_index("ix_wallpapers_deleted_at", table_name="wallpapers")
        op.drop_table("wallpapers")
