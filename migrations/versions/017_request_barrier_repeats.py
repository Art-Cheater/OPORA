"""Шлагбаум и повторные обращения по заявкам.

Revision ID: 017_request_barrier_repeats
Revises: 016_messenger_reply
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017_request_barrier_repeats"
down_revision = "016_messenger_reply"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requests",
        sa.Column(
            "has_barrier",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "requests",
        sa.Column("barrier_phone", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "requests",
        sa.Column(
            "repeat_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "requests",
        sa.Column("repeat_dates", sa.JSON(), nullable=True),
    )

    # Скрыть устаревшие поля и переименовать заявителя в каталоге fields
    op.execute(
        sa.text(
            """
            UPDATE fields AS f
            SET is_visible = false
            FROM modules AS m
            WHERE f.module_id = m.id
              AND m.code = 'requests'
              AND f.code IN ('responsible_id', 'executor_id', 'latitude', 'longitude')
              AND f.deleted_at IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE fields AS f
            SET name = 'Заявитель'
            FROM modules AS m
            WHERE f.module_id = m.id
              AND m.code = 'requests'
              AND f.code = 'applicant_name'
              AND f.deleted_at IS NULL
            """
        )
    )

    bind = op.get_bind()
    module_id = bind.execute(
        sa.text("SELECT id FROM modules WHERE code = 'requests' AND deleted_at IS NULL LIMIT 1")
    ).scalar()
    if module_id is not None:
        import uuid
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        for code, name, sort_order in (
            ("has_barrier", "Шлагбаум", 95),
            ("barrier_phone", "Телефон шлагбаума", 96),
        ):
            exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM fields WHERE module_id = :mid AND code = :code "
                    "AND deleted_at IS NULL LIMIT 1"
                ),
                {"mid": module_id, "code": code},
            ).scalar()
            if exists:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO fields (
                        id, created_at, updated_at, created_by, updated_by, deleted_at,
                        module_id, code, name, sort_order, is_visible
                    ) VALUES (
                        :id, :created_at, :updated_at, NULL, NULL, NULL,
                        :module_id, :code, :name, :sort_order, true
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "created_at": now,
                    "updated_at": now,
                    "module_id": str(module_id),
                    "code": code,
                    "name": name,
                    "sort_order": sort_order,
                },
            )


def downgrade() -> None:
    op.drop_column("requests", "repeat_dates")
    op.drop_column("requests", "repeat_count")
    op.drop_column("requests", "barrier_phone")
    op.drop_column("requests", "has_barrier")
