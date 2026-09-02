"""Удаление ручной связи заявка ↔ дефект.

Revision ID: 042_drop_request_defects
Revises: 041_waybills

Таблица request_defects больше не используется: nearby и план работ
не создают связь между заявкой и дефектом. Заявки, дефекты и путевые
листы не затрагиваются.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "042_drop_request_defects"
down_revision = "041_waybills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "request_defects" not in insp.get_table_names():
        return
    op.drop_table("request_defects")


def downgrade() -> None:
    pass
