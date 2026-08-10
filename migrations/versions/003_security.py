"""Миграция: безопасность — блокировка, журнал входов, роли RBAC

Revision ID: 003_security
Revises: 002_seed_reference_data
Create Date: 2026-08-06

"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003_security"
down_revision = "002_seed_reference_data"
branch_labels = None
depends_on = None

NOW = datetime.now(timezone.utc)

NEW_ROLES = [
    ("admin", "Администратор", "Полный доступ к системе"),
    ("director", "Директор", "Руководство и контроль"),
    ("dispatcher", "Диспетчер", "Диспетчеризация заявок"),
    ("master", "Мастер", "Руководство бригадой"),
    ("executor", "Исполнитель", "Исполнение заявок"),
]

NEW_PERMISSIONS = [
    ("users.block", "Блокировка пользователей", "users"),
    ("profile.view", "Просмотр профиля", "profile"),
    ("profile.edit", "Редактирование профиля", "profile"),
    ("auth.login_logs.view", "Просмотр журнала входов", "auth"),
    ("requests.dispatch", "Диспетчеризация заявок", "requests"),
]

ROLE_PERMISSIONS = {
    "admin": "ALL",
    "director": [
        "users.view", "users.block", "roles.view",
        "profile.view", "profile.edit", "auth.login_logs.view",
        "requests.view", "requests.create", "requests.edit",
        "requests.delete", "requests.approve", "requests.dispatch",
        "projects.view", "projects.create", "projects.edit",
        "contracts.view", "contracts.create", "contracts.edit",
        "audit.view",
    ],
    "dispatcher": [
        "profile.view", "profile.edit", "users.view",
        "requests.view", "requests.create", "requests.edit", "requests.dispatch",
        "projects.view",
    ],
    "master": [
        "profile.view", "profile.edit",
        "requests.view", "requests.create", "requests.edit", "requests.approve",
        "projects.view",
    ],
    "executor": [
        "profile.view", "profile.edit",
        "requests.view", "requests.create", "requests.edit",
        "projects.view",
    ],
}


def upgrade():
    # ── Блокировка пользователей ───────────────────────────────────────
    op.add_column("users", sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("blocked_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("block_reason", sa.Text(), nullable=True))
    op.create_foreign_key("fk_users_blocked_by_users", "users", "users", ["blocked_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_users_is_blocked", "users", ["is_blocked"])

    # ── Журнал входов ──────────────────────────────────────────────────
    op.create_table(
        "login_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_login_logs_created_by_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_login_logs_updated_by_users", ondelete="SET NULL"),
    )
    op.create_index("ix_login_logs_created_at", "login_logs", ["created_at"])
    op.create_index("ix_login_logs_deleted_at", "login_logs", ["deleted_at"])
    op.create_index("ix_login_logs_user_id", "login_logs", ["user_id"])
    op.create_index("ix_login_logs_email", "login_logs", ["email"])
    op.create_index("ix_login_logs_success", "login_logs", ["success"])

    # ── Обновление ролей RBAC ──────────────────────────────────────────
    conn = op.get_bind()

    # Деактивируем устаревшие роли
    conn.execute(sa.text(
        "UPDATE roles SET deleted_at = :now, is_active = false "
        "WHERE code IN ('manager', 'employee', 'viewer') AND deleted_at IS NULL"
    ), {"now": NOW})

    role_ids = {}
    for code, name, desc in NEW_ROLES:
        row = conn.execute(
            sa.text("SELECT id FROM roles WHERE code = :code AND deleted_at IS NULL"),
            {"code": code},
        ).fetchone()
        if row:
            conn.execute(
                sa.text("UPDATE roles SET name = :name, description = :desc, is_active = true WHERE id = :id"),
                {"name": name, "desc": desc, "id": row[0]},
            )
            role_ids[code] = row[0]
        else:
            role_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO roles (id, code, name, description, is_system, is_active, created_at, updated_at) "
                    "VALUES (:id, :code, :name, :desc, true, true, :now, :now)"
                ),
                {"id": role_id, "code": code, "name": name, "desc": desc, "now": NOW},
            )
            role_ids[code] = role_id

    # Новые разрешения
    perm_ids = dict(
        conn.execute(sa.text("SELECT code, id FROM permissions WHERE deleted_at IS NULL")).fetchall()
    )
    for code, name, module in NEW_PERMISSIONS:
        if code not in perm_ids:
            perm_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, name, module, is_active, created_at, updated_at) "
                    "VALUES (:id, :code, :name, :module, true, :now, :now)"
                ),
                {"id": perm_id, "code": code, "name": name, "module": module, "now": NOW},
            )
            perm_ids[code] = perm_id

    # Пересоздаём role_permissions для новых ролей
    for rid in role_ids.values():
        conn.execute(
            sa.text("DELETE FROM role_permissions WHERE role_id = :rid"),
            {"rid": rid},
        )

    all_perm_codes = list(perm_ids.keys())
    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        codes = all_perm_codes if perm_codes == "ALL" else perm_codes
        for perm_code in codes:
            if perm_code not in perm_ids:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (id, role_id, permission_id, created_at, updated_at) "
                    "VALUES (:id, :role_id, :perm_id, :now, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "role_id": role_ids[role_code],
                    "perm_id": perm_ids[perm_code],
                    "now": NOW,
                },
            )

    # Миграция назначений ролей: manager → director, employee → executor
    old_manager = conn.execute(
        sa.text("SELECT id FROM roles WHERE code = 'manager' ORDER BY created_at LIMIT 1")
    ).fetchone()
    old_employee = conn.execute(
        sa.text("SELECT id FROM roles WHERE code = 'employee' ORDER BY created_at LIMIT 1")
    ).fetchone()
    if old_manager and "director" in role_ids:
        conn.execute(
            sa.text("UPDATE user_roles SET role_id = :new_id WHERE role_id = :old_id"),
            {"new_id": role_ids["director"], "old_id": old_manager[0]},
        )
    if old_employee and "executor" in role_ids:
        conn.execute(
            sa.text("UPDATE user_roles SET role_id = :new_id WHERE role_id = :old_id"),
            {"new_id": role_ids["executor"], "old_id": old_employee[0]},
        )


def downgrade():
    op.drop_table("login_logs")
    op.drop_constraint("fk_users_blocked_by_users", "users", type_="foreignkey")
    op.drop_index("ix_users_is_blocked", table_name="users")
    op.drop_column("users", "block_reason")
    op.drop_column("users", "blocked_by")
    op.drop_column("users", "blocked_at")
    op.drop_column("users", "is_blocked")
