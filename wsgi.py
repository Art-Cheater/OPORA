"""WSGI-точка входа для production (gunicorn)."""

from __future__ import annotations

import os

from app import create_app

app = create_app("production")


def _run_container_startup() -> None:
    """Миграции и сиды один раз в мастере Gunicorn (см. preload_app)."""
    if os.getenv("OPORA_SKIP_STARTUP", "").strip().lower() in {"1", "true", "yes"}:
        return

    from flask_migrate import upgrade

    from app.extensions import db
    from app.modules.auth.services import AuthService
    from app.seed.reference_data import ReferenceDataService

    with app.app_context():
        print("Миграции...", flush=True)
        upgrade()
        print("Справочники и администратор...", flush=True)
        ReferenceDataService.seed_all()
        AuthService.create_default_admin()
        db.session.remove()
        print("Запуск воркеров Gunicorn.", flush=True)


_run_container_startup()
