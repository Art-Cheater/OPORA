"""Единый сервис проверки прав доступа."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from app.extensions import db
from app.models.auth.field_definition import FieldDefinition
from app.models.auth.permission import Permission
from app.models.auth.role_field_permission import (
    FIELD_ACCESS_EDIT,
    FIELD_ACCESS_NONE,
    FIELD_ACCESS_VIEW,
    RoleFieldPermission,
)
from app.models.auth.system_module import SystemModule
from app.models.auth.user import User

# Стандартные действия модулей (коды хранятся в permissions.action)
MODULE_ACTIONS: tuple[str, ...] = (
    "view",
    "create",
    "edit",
    "delete",
    "export",
    "print",
    "status_change",
    "file_upload",
    "file_delete",
)

MODULE_ACTION_LABELS: dict[str, str] = {
    "view": "Просмотр",
    "create": "Создание",
    "edit": "Редактирование",
    "delete": "Удаление",
    "export": "Экспорт",
    "print": "Печать",
    "status_change": "Изменение статуса",
    "file_upload": "Загрузка файлов",
    "file_delete": "Удаление файлов",
}

FIELD_ACCESS_LABELS: dict[int, str] = {
    FIELD_ACCESS_NONE: "Нет доступа",
    FIELD_ACCESS_VIEW: "Просмотр",
    FIELD_ACCESS_EDIT: "Редактирование",
}


@dataclass(frozen=True, slots=True)
class CachedModule:
    """Снимок модуля для UI — без привязки к SQLAlchemy-сессии."""

    code: str
    name: str
    sort_order: int = 0


class PermissionService:
    """Централизованная проверка прав модулей и полей."""

    @staticmethod
    def permission_codes(user: User) -> frozenset[str]:
        """Кэш кодов прав на экземпляр пользователя (один раз за запрос)."""
        cached = getattr(user, "_permission_codes_cache", None)
        if cached is not None:
            return cached
        if user.is_admin:
            codes: frozenset[str] = frozenset({"*"})
            setattr(user, "_permission_codes_cache", codes)
            return codes
        collected: set[str] = set()
        for user_role in user.user_roles:
            if user_role.deleted_at is not None or user_role.role is None:
                continue
            role = user_role.role
            if role.deleted_at is not None or not role.is_active:
                continue
            for role_perm in role.role_permissions:
                if role_perm.deleted_at is not None or role_perm.permission is None:
                    continue
                perm = role_perm.permission
                if perm.deleted_at is None and perm.is_active and perm.code:
                    collected.add(perm.code)
        codes = frozenset(collected)
        setattr(user, "_permission_codes_cache", codes)
        return codes

    @staticmethod
    def has_permission(user: User, permission_code: str) -> bool:
        if user.is_admin:
            return True
        return permission_code in PermissionService.permission_codes(user)

    @staticmethod
    def has_module_action(user: User, module_code: str, action: str) -> bool:
        return PermissionService.has_permission(user, f"{module_code}.{action}")

    @classmethod
    def _field_rules(cls, user: User, module: str) -> list[RoleFieldPermission]:
        rules: list[RoleFieldPermission] = []
        for role in user.roles:
            for rule in role.field_permissions:
                if rule.deleted_at is None and rule.module == module:
                    rules.append(rule)
        return rules

    @classmethod
    def has_field_rules(cls, user: User, module: str) -> bool:
        return bool(cls._field_rules(user, module))

    @classmethod
    def field_access_level(cls, user: User, module: str, field_name: str) -> int:
        if user.is_admin:
            return FIELD_ACCESS_EDIT
        view_perm = f"{module}.view"
        edit_perm = f"{module}.edit"
        if not cls.has_permission(user, view_perm) and not cls.has_permission(user, edit_perm):
            return FIELD_ACCESS_NONE

        rules = cls._field_rules(user, module)
        if not rules:
            return FIELD_ACCESS_EDIT if cls.has_permission(user, edit_perm) else FIELD_ACCESS_VIEW

        max_level = FIELD_ACCESS_NONE
        for rule in rules:
            if rule.field_name != field_name:
                continue
            level = rule.access_level
            if level >= FIELD_ACCESS_EDIT or (rule.can_edit and rule.can_view):
                level = FIELD_ACCESS_EDIT
            elif level >= FIELD_ACCESS_VIEW or rule.can_view:
                level = max(level, FIELD_ACCESS_VIEW)
            max_level = max(max_level, level)
        return max_level

    @classmethod
    def can_view_field(cls, user: User, module: str, field_name: str) -> bool:
        return cls.field_access_level(user, module, field_name) >= FIELD_ACCESS_VIEW

    @classmethod
    def can_edit_field(cls, user: User, module: str, field_name: str) -> bool:
        return cls.field_access_level(user, module, field_name) >= FIELD_ACCESS_EDIT

    @classmethod
    def resolve_field(cls, user: User, module: str, field_name: str, submitted, entity=None):
        if cls.can_edit_field(user, module, field_name):
            return submitted
        if entity is not None:
            return getattr(entity, field_name, submitted)
        # Создание: без права на поле игнорируем клиентское значение (не IDOR через POST).
        return None

    @classmethod
    def editable_fields(cls, user: User, module: str) -> set[str] | None:
        if user.is_admin:
            return None
        if not cls.has_permission(user, f"{module}.edit"):
            return set()
        rules = cls._field_rules(user, module)
        if not rules:
            return None
        return {
            rule.field_name
            for rule in rules
            if cls.field_access_level(user, module, rule.field_name) >= FIELD_ACCESS_EDIT
        }

    @staticmethod
    @lru_cache(maxsize=1)
    def _cached_modules() -> tuple[CachedModule, ...]:
        rows = db.session.execute(
            db.select(SystemModule.code, SystemModule.name, SystemModule.sort_order)
            .where(SystemModule.active_filter(), SystemModule.is_active.is_(True))
            .order_by(SystemModule.sort_order.asc(), SystemModule.name.asc())
        ).all()
        return tuple(
            CachedModule(code=code, name=name, sort_order=sort_order or 0)
            for code, name, sort_order in rows
        )

    @classmethod
    def clear_cache(cls) -> None:
        cls._cached_modules.cache_clear()
        cls.get_module_fields.cache_clear()
        cls.get_module_permissions.cache_clear()
        try:
            from app.core.builtin_field_service import BuiltinFieldService

            BuiltinFieldService.clear_cache()
        except Exception:
            pass
        try:
            from app.core.field_catalog import clear_catalog_cache

            clear_catalog_cache()
        except Exception:
            pass

    @staticmethod
    def get_modules() -> list[CachedModule]:
        return list(PermissionService._cached_modules())

    @staticmethod
    @lru_cache(maxsize=32)
    def get_module_fields(module_code: str) -> dict[str, str]:
        rows = db.session.execute(
            db.select(FieldDefinition.code, FieldDefinition.name)
            .join(SystemModule, FieldDefinition.module_id == SystemModule.id)
            .where(
                SystemModule.code == module_code,
                SystemModule.active_filter(),
                FieldDefinition.active_filter(),
                FieldDefinition.is_active.is_(True),
            )
            .order_by(FieldDefinition.sort_order.asc(), FieldDefinition.name.asc())
        ).all()
        return {code: name for code, name in rows}

    @staticmethod
    @lru_cache(maxsize=32)
    def get_module_permissions(module_code: str) -> dict[str, str]:
        """{action: permission_code} — без ORM-объектов в кэше."""
        rows = db.session.execute(
            db.select(Permission.action, Permission.code)
            .where(
                Permission.module == module_code,
                Permission.active_filter(),
                Permission.is_active.is_(True),
            )
            .order_by(Permission.action.asc(), Permission.name.asc())
        ).all()
        return {action: code for action, code in rows}

    @staticmethod
    def get_permissions_matrix() -> dict[str, dict[str, Permission]]:
        """{module_code: {action: Permission}}."""
        perms = db.session.scalars(
            db.select(Permission).where(
                Permission.active_filter(),
                Permission.is_active.is_(True),
            )
        )
        matrix: dict[str, dict[str, Permission]] = {}
        for perm in perms:
            matrix.setdefault(perm.module, {})[perm.action] = perm
        return matrix

    @staticmethod
    def module_labels() -> dict[str, str]:
        return {m.code: m.name for m in PermissionService.get_modules()}

    @staticmethod
    def module_fields_dict(module_code: str) -> dict[str, str]:
        builtin = dict(PermissionService.get_module_fields(module_code))
        from app.core.custom_field_service import CustomFieldService

        custom = CustomFieldService.custom_fields_dict(module_code)
        return {**builtin, **custom}

    @staticmethod
    def all_module_fields_dict() -> dict[str, dict[str, str]]:
        from app.core.field_catalog import catalog_fields_dict

        return catalog_fields_dict()

    @staticmethod
    def permission_code(module_code: str, action: str) -> str:
        return f"{module_code}.{action}"
