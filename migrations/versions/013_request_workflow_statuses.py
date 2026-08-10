"""Обновление статусов заявок под workflow диспетчер → АБ → мастер.

Revision ID: 013_request_workflow_statuses
Revises: 012_custom_fields
Create Date: 2026-08-09
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013_request_workflow_statuses"
down_revision = "012_custom_fields"
branch_labels = None
depends_on = None

# (code, name, description, color, sort_order, is_final)
NEW_STATUSES = [
    ("new", "Новая", "Заявка создана диспетчером", "#6C757D", 10, False),
    (
        "emergency_dispatched",
        "Выехала аварийная бригада",
        "Аварийная бригада выехала на место",
        "#FFC107",
        20,
        False,
    ),
    (
        "accepted_by_master",
        "Передана мастеру",
        "Диспетчер передал заявку выбранному мастеру",
        "#F57C00",
        30,
        False,
    ),
    ("in_progress", "В работе", "Заявка выполняется мастером", "#F57C00", 40, False),
    ("completed", "Выполнено", "Мастер отметил заявку выполненной", "#2E7D32", 50, True),
    ("cancelled", "Отменена", "Заявка отменена", "#ADB5BD", 60, True),
]

# Старые коды → новый код
REMAP = {
    "draft": "new",
    "submitted": "new",
    "in_review": "new",
    "approved": "new",
    "rejected": "cancelled",
}


def _utcnow():
    return datetime.now(timezone.utc)


def upgrade():
    conn = op.get_bind()
    statuses = sa.table(
        "request_statuses",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("created_by", postgresql.UUID(as_uuid=True)),
        sa.column("updated_by", postgresql.UUID(as_uuid=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("is_active", sa.Boolean()),
        sa.column("code", sa.String(50)),
        sa.column("name", sa.String(100)),
        sa.column("description", sa.Text()),
        sa.column("color", sa.String(20)),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_final", sa.Boolean()),
    )
    requests = sa.table(
        "requests",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("status_id", postgresql.UUID(as_uuid=True)),
    )

    rows = conn.execute(
        sa.text("SELECT id, code FROM request_statuses WHERE deleted_at IS NULL")
    ).fetchall()
    by_code = {row.code: row.id for row in rows}
    now = _utcnow()

    # Обновить/создать целевые статусы
    for code, name, desc, color, order, is_final in NEW_STATUSES:
        if code in by_code:
            conn.execute(
                statuses.update()
                .where(statuses.c.id == by_code[code])
                .values(
                    name=name,
                    description=desc,
                    color=color,
                    sort_order=order,
                    is_final=is_final,
                    is_active=True,
                    updated_at=now,
                    deleted_at=None,
                )
            )
        else:
            new_id = uuid.uuid4()
            conn.execute(
                statuses.insert().values(
                    id=new_id,
                    created_at=now,
                    updated_at=now,
                    created_by=None,
                    updated_by=None,
                    deleted_at=None,
                    is_active=True,
                    code=code,
                    name=name,
                    description=desc,
                    color=color,
                    sort_order=order,
                    is_final=is_final,
                )
            )
            by_code[code] = new_id

    # Переименовать draft → new, если new ещё не было, а draft есть
    if "draft" in by_code and "new" in by_code and by_code["draft"] != by_code["new"]:
        # заявки с draft уже перемапятся ниже
        pass

    # Ремап заявок со старых статусов
    for old_code, new_code in REMAP.items():
        if old_code not in by_code or new_code not in by_code:
            continue
        if by_code[old_code] == by_code[new_code]:
            continue
        conn.execute(
            requests.update()
            .where(requests.c.status_id == by_code[old_code])
            .values(status_id=by_code[new_code])
        )

    # Деактивировать устаревшие статусы (не из NEW_STATUSES)
    keep = {item[0] for item in NEW_STATUSES}
    for code, status_id in by_code.items():
        if code not in keep:
            conn.execute(
                statuses.update()
                .where(statuses.c.id == status_id)
                .values(is_active=False, updated_at=now)
            )

    # Выдать executor право requests.dispatch (выезд АБ), если роль и permission уже есть
    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, created_at, updated_at, role_id, permission_id)
            SELECT gen_random_uuid(), :now, :now, r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.code = 'executor'
              AND r.deleted_at IS NULL
              AND p.code = 'requests.dispatch'
              AND p.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM role_permissions rp
                  WHERE rp.role_id = r.id
                    AND rp.permission_id = p.id
                    AND rp.deleted_at IS NULL
              )
            """
        ),
        {"now": now},
    )


def downgrade():
    # Обратный откат статусов не восстанавливает старые заявки полностью —
    # только реактивируем прежние коды при наличии.
    conn = op.get_bind()
    now = _utcnow()
    conn.execute(
        sa.text(
            """
            UPDATE request_statuses
            SET is_active = true, updated_at = :now
            WHERE code IN ('draft', 'submitted', 'in_review', 'approved', 'rejected')
              AND deleted_at IS NULL
            """
        ),
        {"now": now},
    )
