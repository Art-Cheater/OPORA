"""Общие фикстуры pytest для HTTP/RBAC тестов."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.modules.auth.services import AuthService
from app.seed.reference_data import ReferenceDataService


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    existing_url = os.getenv("TEST_DATABASE_URL", "").strip()
    use_postgres = existing_url.startswith("postgresql")
    if use_postgres:
        monkeypatch.setenv("USE_SQLITE", "0")
        monkeypatch.setenv("TEST_DATABASE_URL", existing_url)
    else:
        db_path = tmp_path / "test.db"
        monkeypatch.setenv("TEST_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
        monkeypatch.setenv("USE_SQLITE", "1")

    application = create_app("testing")
    application.config["WTF_CSRF_ENABLED"] = False
    upload_dir = Path(tempfile.mkdtemp(prefix="opora_test_uploads_"))
    application.config["UPLOAD_FOLDER"] = upload_dir

    with application.app_context():
        if use_postgres:
            db.session.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            db.session.execute(text("CREATE SCHEMA public"))
            db.session.commit()
        db.create_all()
        ReferenceDataService.seed_all()
        ReferenceDataService.sync_security_roles()
        AuthService.create_default_admin()
        AuthService.create_user(
            "dispatcher@test.local", "pass12345", "Диспетчер QA", "dispatcher"
        )
        AuthService.create_user("master@test.local", "pass12345", "Мастер QA", "master")
        AuthService.create_user(
            "executor@test.local", "pass12345", "Исполнитель QA", "executor"
        )
        yield application
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_client(client):
    client.post(
        "/auth/login",
        data={"email": "admin@opora.ru", "password": "admin123", "submit": "Войти"},
        follow_redirects=True,
    )
    return client
