"""Хуки автоматической записи журнала действий."""

from __future__ import annotations

from flask import Flask, g, request
from flask_login import current_user

from app.core.audit_service import SKIP_AUTO_AUDIT_ENDPOINTS, AuditService


def register_audit_hooks(app: Flask) -> None:
    """Регистрирует автоматическую запись действий пользователя."""

    @app.after_request
    def auto_audit_log(response):
        if not current_user.is_authenticated:
            return response
        if response.status_code >= 400:
            return response
        if getattr(g, "audit_logged", False):
            return response
        if request.endpoint is None or request.endpoint in SKIP_AUTO_AUDIT_ENDPOINTS:
            return response
        # GET не пишем: лишний COMMIT на каждый просмотр карточки сильно тормозит навигацию.
        # Явные действия модулей пишут аудит сами через AuditService.log(...).
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return response

        try:
            AuditService.log_http_action(current_user.id, request.endpoint, request.method)
            from app.extensions import db

            db.session.commit()
        except Exception:
            from app.extensions import db

            db.session.rollback()

        return response
