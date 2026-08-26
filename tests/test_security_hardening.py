"""Regression: privilege escalation, path traversal, wipe gate, logout CSRF."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.core.upload_utils import resolve_storage_path
from app.extensions import db
from app.models.auth.associations import RolePermission, UserRole
from app.models.auth.constants import ROLE_ADMIN
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.auth.user import User
from app.modules.employees.services import EmployeePayload, EmployeeService


def _grant_user_perms(app, email: str, codes: list[str]) -> uuid.UUID:
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == email))
        assert user is not None
        role = Role(
            code=f"hr_{uuid.uuid4().hex[:8]}",
            name="HR test",
            is_system=False,
            created_by=user.id,
            updated_by=user.id,
        )
        db.session.add(role)
        db.session.flush()
        perms = list(
            db.session.scalars(
                db.select(Permission).where(
                    Permission.active_filter(),
                    Permission.code.in_(codes),
                )
            )
        )
        assert perms
        for perm in perms:
            db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()
        return user.id


def test_non_admin_cannot_assign_admin_role(app, client):
    actor_id = _grant_user_perms(
        app,
        "dispatcher@test.local",
        ["users.view", "users.create", "users.edit", "users.delete"],
    )
    with app.app_context():
        admin_role = db.session.scalar(db.select(Role).where(Role.code == ROLE_ADMIN))
        assert admin_role is not None
        with pytest.raises(ValidationError, match="администратора"):
            EmployeeService.create_employee(
                EmployeePayload(
                    email="evil-admin@test.local",
                    full_name="Evil Admin",
                    phone=None,
                    position_id=None,
                    department=None,
                    role_ids=[admin_role.id],
                    password="pass12345",
                ),
                actor_id,
            )


def test_non_admin_cannot_edit_admin_user(app):
    actor_id = _grant_user_perms(
        app,
        "master@test.local",
        ["users.view", "users.edit"],
    )
    with app.app_context():
        admin = db.session.scalar(db.select(User).where(User.email == "admin@opora.ru"))
        executor_role = db.session.scalar(db.select(Role).where(Role.code == "executor"))
        assert admin is not None and executor_role is not None
        with pytest.raises(ValidationError, match="администратора"):
            EmployeeService.update_employee(
                admin,
                EmployeePayload(
                    email=admin.email,
                    full_name=admin.full_name,
                    phone=admin.phone,
                    position_id=admin.position_id,
                    department=admin.department,
                    role_ids=[executor_role.id],
                    password="hacked-password",
                ),
                actor_id,
            )


def test_objects_wipe_requires_admin(client, app):
    client.post(
        "/auth/login",
        data={"email": "dispatcher@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    _grant_user_perms(app, "dispatcher@test.local", ["objects.view", "objects.delete"])
    denied = client.post("/objects/wipe")
    assert denied.status_code == 403


def test_logout_get_does_not_end_session(admin_client):
    page = admin_client.get("/auth/logout")
    assert page.status_code == 200
    assert "Выйти из системы" in page.get_data(as_text=True)
    home = admin_client.get("/", follow_redirects=False)
    assert home.status_code == 200


def test_logout_post_ends_session(admin_client):
    out = admin_client.post("/auth/logout", follow_redirects=False)
    assert out.status_code in (302, 303)
    again = admin_client.get("/", follow_redirects=False)
    assert again.status_code in (302, 401)


def test_resolve_storage_path_blocks_traversal(app):
    with app.app_context():
        root: Path = app.config["UPLOAD_FOLDER"]
        safe = root / "docs"
        safe.mkdir(parents=True, exist_ok=True)
        (safe / "ok.txt").write_text("x", encoding="utf-8")
        ok = resolve_storage_path("docs/ok.txt")
        assert ok.is_file()
        with pytest.raises(FileNotFoundError):
            resolve_storage_path("../ok.txt")
        with pytest.raises(FileNotFoundError):
            resolve_storage_path("docs/../../etc/passwd")
        with pytest.raises(FileNotFoundError):
            resolve_storage_path("/etc/passwd")


def test_security_headers_present(admin_client):
    resp = admin_client.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "frame-ancestors" in (resp.headers.get("Content-Security-Policy") or "")


def test_admin_can_still_create_employee(admin_client, app):
    with app.app_context():
        executor = db.session.scalar(db.select(Role).where(Role.code == "executor"))
        assert executor is not None
        role_id = str(executor.id)
    created = admin_client.post(
        "/employees/new",
        data={
            "email": "safe.user@test.local",
            "full_name": "Безопасный Пользователь",
            "phone": "",
            "department": "QA",
            "position_id": "",
            "role_ids": [role_id],
            "password": "pass12345",
            "submit": "1",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "safe.user@test.local"))
        assert user is not None
        assert not user.is_admin
