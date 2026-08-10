"""Проверка прав на уровне полей модулей (обратная совместимость)."""

from __future__ import annotations

from app.core.permission_service import PermissionService
from app.models.auth.user import User


class FieldPermissionService(PermissionService):
    """Алиас для существующего кода."""

    @classmethod
    def resolve_field(cls, user: User, module: str, field_name: str, submitted, entity=None):
        return PermissionService.resolve_field(user, module, field_name, submitted, entity)
