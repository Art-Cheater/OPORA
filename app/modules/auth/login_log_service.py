"""Сервис журнала входов."""

from __future__ import annotations

import uuid

from flask import request

from app.extensions import db
from app.models.auth.login_log import LoginLog
from app.models.auth.user import User


class LoginLogService:
    """Запись и чтение журнала входов."""

    @staticmethod
    def _client_ip() -> str | None:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr

    @staticmethod
    def _user_agent() -> str | None:
        return request.headers.get("User-Agent")

    @classmethod
    def log_attempt(
        cls,
        email: str,
        success: bool,
        user: User | None = None,
        failure_reason: str | None = None,
    ) -> LoginLog:
        """Фиксирует попытку входа в систему."""
        entry = LoginLog(
            user_id=user.id if user else None,
            email=email.lower().strip(),
            success=success,
            ip_address=cls._client_ip(),
            user_agent=cls._user_agent(),
            failure_reason=failure_reason,
        )
        db.session.add(entry)
        return entry

    @staticmethod
    def get_user_logs(user_id: uuid.UUID, limit: int = 20) -> list[LoginLog]:
        """Возвращает последние записи журнала для пользователя."""
        return list(
            db.session.scalars(
                db.select(LoginLog)
                .where(LoginLog.user_id == user_id, LoginLog.active_filter())
                .order_by(LoginLog.created_at.desc())
                .limit(limit)
            )
        )

    @staticmethod
    def get_all_logs(limit: int = 100) -> list[LoginLog]:
        """Возвращает последние записи журнала (для администраторов)."""
        return list(
            db.session.scalars(
                db.select(LoginLog)
                .where(LoginLog.active_filter())
                .order_by(LoginLog.created_at.desc())
                .limit(limit)
            )
        )
