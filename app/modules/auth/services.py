"""Сервис аутентификации — бизнес-логика."""

from __future__ import annotations

import uuid

from flask import current_app
from flask_login import login_user, logout_user

from app.core.audit_service import AuditService
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import hash_password
from app.extensions import db
from app.models.auth.associations import UserRole
from app.models.auth.constants import ROLE_ADMIN, ROLE_EXECUTOR
from app.models.auth.role import Role
from app.models.auth.user import User
from app.models.base import utcnow
from app.models.enums import AuditAction, EntityType
from app.modules.auth.login_log_service import LoginLogService
from app.modules.auth.repositories import UserRepository


class AuthService:
    """Сервис аутентификации и управления пользователями."""

    @staticmethod
    def authenticate(email: str, password: str, remember: bool = False) -> User:
        """Аутентификация пользователя по email и паролю."""
        email = email.lower().strip()
        user = UserRepository.get_by_email(email)

        if user is None:
            LoginLogService.log_attempt(email, success=False, failure_reason="user_not_found")
            db.session.commit()
            raise AuthenticationError("Неверный email или пароль.")

        if user.is_blocked:
            LoginLogService.log_attempt(
                email, success=False, user=user, failure_reason="user_blocked"
            )
            db.session.commit()
            raise AuthenticationError("Учётная запись заблокирована. Обратитесь к администратору.")

        if not user.is_active:
            LoginLogService.log_attempt(
                email, success=False, user=user, failure_reason="user_inactive"
            )
            db.session.commit()
            raise AuthenticationError("Учётная запись деактивирована.")

        if not user.check_password(password):
            LoginLogService.log_attempt(
                email, success=False, user=user, failure_reason="invalid_password"
            )
            db.session.commit()
            raise AuthenticationError("Неверный email или пароль.")

        AuthService.rehash_password_if_needed(user, password)
        user.last_login_at = utcnow()
        LoginLogService.log_attempt(email, success=True, user=user)
        AuditService.log(
            user_id=user.id,
            action=AuditAction.LOGIN.value,
            entity_type=EntityType.USER.value,
            entity_id=user.id,
            description=f"Вход в систему: {user.email}",
        )
        db.session.commit()

        login_user(user, remember=remember)
        return user

    @staticmethod
    def logout() -> None:
        """Выход пользователя из системы."""
        from flask_login import current_user

        if current_user.is_authenticated:
            AuditService.log(
                user_id=current_user.id,
                action=AuditAction.LOGOUT.value,
                entity_type=EntityType.USER.value,
                entity_id=current_user.id,
                description=f"Выход из системы: {current_user.email}",
                commit=True,
            )
        logout_user()

    @staticmethod
    def change_password(user: User, current_password: str, new_password: str) -> None:
        """Смена пароля текущего пользователя."""
        if not user.check_password(current_password):
            raise AuthenticationError("Текущий пароль указан неверно.")

        if current_password == new_password:
            raise AuthenticationError("Новый пароль должен отличаться от текущего.")

        user.set_password(new_password)
        user.updated_by = user.id
        db.session.commit()

    @staticmethod
    def block_user(
        user: User,
        blocked_by: uuid.UUID,
        reason: str | None = None,
    ) -> User:
        """Блокирует пользователя."""
        if user.id == blocked_by:
            raise AuthorizationError("Нельзя заблокировать собственную учётную запись.")

        user.block(blocked_by=blocked_by, reason=reason)
        user.updated_by = blocked_by
        db.session.commit()
        return user

    @staticmethod
    def unblock_user(user: User, unblocked_by: uuid.UUID) -> User:
        """Разблокирует пользователя."""
        user.unblock()
        user.updated_by = unblocked_by
        db.session.commit()
        return user

    @staticmethod
    def create_user(
        email: str,
        password: str,
        full_name: str,
        role_code: str = ROLE_EXECUTOR,
    ) -> User:
        """Создание нового пользователя с назначением роли."""
        email = email.lower().strip()

        if UserRepository.exists_by_email(email):
            raise AuthenticationError("Пользователь с таким email уже существует.")

        role = db.session.scalar(
            db.select(Role).where(Role.code == role_code, Role.active_filter())
        )
        if role is None:
            raise AuthenticationError(f"Роль «{role_code}» не найдена.")

        user = User(email=email, full_name=full_name.strip())
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()
        return user

    @staticmethod
    def create_default_admin() -> User | None:
        """Создаёт администратора по умолчанию из конфигурации."""
        email = current_app.config["ADMIN_EMAIL"]

        admin_role = db.session.scalar(
            db.select(Role).where(Role.code == ROLE_ADMIN, Role.active_filter())
        )
        if admin_role is None:
            return None

        existing = UserRepository.get_by_email(email)
        if existing is not None:
            AuthService.assign_role(existing, ROLE_ADMIN)
            return existing

        user = User(
            email=email,
            full_name=current_app.config["ADMIN_FULL_NAME"],
        )
        user.set_password(current_app.config["ADMIN_PASSWORD"])
        db.session.add(user)
        db.session.flush()

        db.session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        db.session.commit()
        return user

    @staticmethod
    def repair_users_without_roles(*, assign_admin: bool = True) -> int:
        """Назначает роль admin пользователям без ролей (восстановление доступа)."""
        if not assign_admin:
            return 0
        users = db.session.scalars(db.select(User).where(User.active_filter())).all()
        fixed = 0
        for user in users:
            if user.roles:
                continue
            AuthService.assign_role(user, ROLE_ADMIN)
            fixed += 1
        return fixed

    @staticmethod
    def assign_role(user: User, role_code: str) -> UserRole:
        """Назначает роль пользователю."""
        role = db.session.scalar(
            db.select(Role).where(Role.code == role_code, Role.active_filter())
        )
        if role is None:
            raise AuthenticationError(f"Роль «{role_code}» не найдена.")

        existing = db.session.scalar(
            db.select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
                UserRole.active_filter(),
            )
        )
        if existing is not None:
            return existing

        user_role = UserRole(user_id=user.id, role_id=role.id)
        db.session.add(user_role)
        db.session.commit()
        return user_role

    @staticmethod
    def rehash_password_if_needed(user: User, password: str) -> None:
        """Перехеширует пароль в bcrypt при входе (миграция со старых хешей)."""
        if user.password_hash.startswith("$2"):
            return
        user.password_hash = hash_password(password)
        db.session.commit()
