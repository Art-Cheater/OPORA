"""Декораторы и утилиты безопасности."""

from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user


def _ensure_authenticated():
    if not current_user.is_authenticated:
        abort(401)


def _ensure_can_access():
    """Проверяет, что пользователь не заблокирован и активен."""
    _ensure_authenticated()
    if not current_user.can_login:
        abort(403)


def role_required(*roles: str):
    """Декоратор: доступ только для указанных ролей (любая из списка)."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            _ensure_can_access()
            if not current_user.has_any_role(*roles):
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def all_roles_required(*roles: str):
    """Декоратор: пользователь должен иметь все указанные роли."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            _ensure_can_access()
            if not all(current_user.has_role(role) for role in roles):
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def permission_required(permission_code: str):
    """Декоратор: доступ только при наличии разрешения."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            _ensure_can_access()
            if not current_user.has_permission(permission_code):
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def any_permission_required(*permission_codes: str):
    """Декоратор: доступ при наличии любого из разрешений."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            _ensure_can_access()
            if not current_user.has_any_permission(*permission_codes):
                abort(403)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(view_func):
    """Декоратор: доступ только для администратора."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        _ensure_can_access()
        if not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)

    return wrapper
