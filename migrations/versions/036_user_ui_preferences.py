"""Пользовательские настройки UI: тема и фон интерфейса.

Revision ID: 036_user_ui_preferences
Revises: 035_integrity_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_user_ui_preferences"
down_revision = "035_integrity_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("users")} if "users" in insp.get_table_names() else set()
    if "ui_theme" not in cols:
        op.add_column("users", sa.Column("ui_theme", sa.String(length=10), nullable=True))
    if "ui_background" not in cols:
        op.add_column(
            "users",
            sa.Column("ui_background", sa.String(length=64), nullable=False, server_default="none"),
        )
    if "ui_background_key" not in cols:
        op.add_column("users", sa.Column("ui_background_key", sa.String(length=500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("users")} if "users" in insp.get_table_names() else set()
    if "ui_background_key" in cols:
        op.drop_column("users", "ui_background_key")
    if "ui_background" in cols:
        op.drop_column("users", "ui_background")
    if "ui_theme" in cols:
        op.drop_column("users", "ui_theme")
