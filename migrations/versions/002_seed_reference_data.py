"""Начальные справочные данные: статусы, роли, разрешения

Revision ID: 002_seed_reference_data
Revises: 001_initial
Create Date: 2026-08-06

"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002_seed_reference_data"
down_revision = "001_initial"
branch_labels = None
depends_on = None

NOW = datetime.now(timezone.utc)

REQUEST_STATUSES = [
    ("draft", "Черновик", "Заявка создана, но не отправлена", "#6c757d", 10, False),
    ("submitted", "Подана", "Заявка отправлена на рассмотрение", "#0d6efd", 20, False),
    ("in_review", "На рассмотрении", "Заявка находится на рассмотрении", "#ffc107", 30, False),
    ("approved", "Одобрена", "Заявка одобрена", "#198754", 40, False),
    ("rejected", "Отклонена", "Заявка отклонена", "#dc3545", 50, True),
    ("in_progress", "В работе", "Заявка выполняется", "#0dcaf0", 60, False),
    ("completed", "Завершена", "Заявка успешно выполнена", "#198754", 70, True),
    ("cancelled", "Отменена", "Заявка отменена", "#6c757d", 80, True),
]

ROLES = [
    ("admin", "Администратор", "Полный доступ к системе", True),
    ("manager", "Руководитель", "Управление подразделением и проектами", True),
    ("employee", "Сотрудник", "Стандартный пользователь системы", True),
    ("viewer", "Наблюдатель", "Только просмотр данных", True),
]

PERMISSIONS = [
    ("users.view", "Просмотр пользователей", "users"),
    ("users.create", "Создание пользователей", "users"),
    ("users.edit", "Редактирование пользователей", "users"),
    ("users.delete", "Удаление пользователей", "users"),
    ("roles.view", "Просмотр ролей", "roles"),
    ("roles.manage", "Управление ролями", "roles"),
    ("requests.view", "Просмотр заявок", "requests"),
    ("requests.create", "Создание заявок", "requests"),
    ("requests.edit", "Редактирование заявок", "requests"),
    ("requests.delete", "Удаление заявок", "requests"),
    ("requests.approve", "Одобрение заявок", "requests"),
    ("projects.view", "Просмотр проектов", "projects"),
    ("projects.create", "Создание проектов", "projects"),
    ("projects.edit", "Редактирование проектов", "projects"),
    ("projects.delete", "Удаление проектов", "projects"),
    ("contracts.view", "Просмотр договоров", "contracts"),
    ("contracts.create", "Создание договоров", "contracts"),
    ("contracts.edit", "Редактирование договоров", "contracts"),
    ("contracts.delete", "Удаление договоров", "contracts"),
    ("audit.view", "Просмотр журнала аудита", "audit"),
]

ROLE_PERMISSIONS = {
    "admin": [p[0] for p in PERMISSIONS],
    "manager": [
        "users.view", "requests.view", "requests.create", "requests.edit",
        "requests.approve", "projects.view", "projects.create", "projects.edit",
        "contracts.view", "contracts.create", "contracts.edit",
    ],
    "employee": [
        "requests.view", "requests.create", "requests.edit",
        "projects.view", "contracts.view",
    ],
    "viewer": [
        "users.view", "requests.view", "projects.view", "contracts.view",
    ],
}


def upgrade():
    status_table = sa.table(
        "request_statuses",
        sa.column("id", postgresql.UUID),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("color", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_final", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        status_table,
        [
            {
                "id": uuid.uuid4(),
                "code": code,
                "name": name,
                "description": desc,
                "color": color,
                "sort_order": order,
                "is_final": is_final,
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
            for code, name, desc, color, order, is_final in REQUEST_STATUSES
        ],
    )

    role_ids = {}
    role_table = sa.table(
        "roles",
        sa.column("id", postgresql.UUID),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    for code, name, desc, is_system in ROLES:
        role_id = uuid.uuid4()
        role_ids[code] = role_id
        op.execute(
            role_table.insert().values(
                id=role_id,
                code=code,
                name=name,
                description=desc,
                is_system=is_system,
                is_active=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    permission_ids = {}
    perm_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("module", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    for code, name, module in PERMISSIONS:
        perm_id = uuid.uuid4()
        permission_ids[code] = perm_id
        op.execute(
            perm_table.insert().values(
                id=perm_id,
                code=code,
                name=name,
                module=module,
                is_active=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    rp_table = sa.table(
        "role_permissions",
        sa.column("id", postgresql.UUID),
        sa.column("role_id", postgresql.UUID),
        sa.column("permission_id", postgresql.UUID),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        for perm_code in perm_codes:
            op.execute(
                rp_table.insert().values(
                    id=uuid.uuid4(),
                    role_id=role_ids[role_code],
                    permission_id=permission_ids[perm_code],
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


def downgrade():
    op.execute(sa.text("DELETE FROM role_permissions"))
    op.execute(sa.text("DELETE FROM permissions"))
    op.execute(sa.text("DELETE FROM roles"))
    op.execute(sa.text("DELETE FROM request_statuses"))
