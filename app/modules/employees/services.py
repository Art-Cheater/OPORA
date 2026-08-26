"""Сервисы модуля сотрудников."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.auth.associations import UserRole
from app.models.auth.constants import ROLE_ADMIN
from app.models.auth.role import Role
from app.models.auth.user import User
from app.models.enums import AuditAction, EntityType


@dataclass
class EmployeePayload:
    email: str
    full_name: str
    phone: str | None
    position_id: uuid.UUID | None
    department: str | None
    role_ids: list[uuid.UUID]
    password: str | None = None


class EmployeeService:
    """CRUD сотрудников."""

    @staticmethod
    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @staticmethod
    def _sync_position_label(user: User) -> None:
        if user.position_id is not None:
            from app.models.auth.position import Position

            pos = db.session.get(Position, user.position_id)
            user.position = pos.name if pos else None
        else:
            user.position = None

    @classmethod
    def _actor(cls, actor_id: uuid.UUID) -> User:
        actor = db.session.get(User, actor_id)
        if actor is None or actor.deleted_at is not None:
            raise ValidationError("Пользователь не найден.")
        return actor

    @classmethod
    def _assert_privileged_changes(
        cls,
        actor: User,
        *,
        target: User | None,
        role_ids: list[uuid.UUID],
        password: str | None,
    ) -> None:
        """Не-админ не может трогать админов и назначать роль admin."""
        if target is not None and target.is_admin and not actor.is_admin:
            raise ValidationError("Редактировать администратора может только администратор.")
        if password and target is not None and target.is_admin and not actor.is_admin:
            raise ValidationError("Сбрасывать пароль администратора может только администратор.")
        if not role_ids:
            return
        roles = list(
            db.session.scalars(
                db.select(Role).where(Role.id.in_(role_ids), Role.active_filter())
            )
        )
        if any(r.code == ROLE_ADMIN for r in roles) and not actor.is_admin:
            raise ValidationError("Назначать роль администратора может только администратор.")

    @classmethod
    def _sync_roles(cls, user: User, role_ids: list[uuid.UUID]) -> None:
        active_roles = {
            ur.role_id: ur
            for ur in user.user_roles
            if ur.deleted_at is None and ur.role_id is not None
        }
        desired = set(role_ids)

        for role_id, ur in list(active_roles.items()):
            if role_id not in desired:
                ur.soft_delete()

        for role_id in desired:
            if role_id not in active_roles:
                db.session.add(UserRole(user_id=user.id, role_id=role_id))

    @classmethod
    def create_employee(cls, payload: EmployeePayload, user_id: uuid.UUID) -> User:
        actor = cls._actor(user_id)
        email = (payload.email or "").lower().strip()
        if not email:
            raise ValidationError("Email обязателен.")
        existing = db.session.scalar(
            db.select(User).where(User.email == email, User.active_filter())
        )
        if existing is not None:
            raise ValidationError("Сотрудник с таким email уже существует.")
        if not payload.role_ids:
            raise ValidationError("Выберите хотя бы одну роль.")
        if not payload.password:
            raise ValidationError("Пароль обязателен.")
        if not (payload.full_name or "").strip():
            raise ValidationError("ФИО обязательно.")
        cls._assert_privileged_changes(
            actor, target=None, role_ids=payload.role_ids, password=payload.password
        )

        user = User(
            email=email,
            full_name=payload.full_name.strip(),
            phone=cls._normalize(payload.phone),
            position_id=payload.position_id,
            department=cls._normalize(payload.department),
            created_by=user_id,
            updated_by=user_id,
        )
        user.set_password(payload.password)
        db.session.add(user)
        db.session.flush()
        cls._sync_position_label(user)
        cls._sync_roles(user, payload.role_ids)

        AuditService.log(
            user_id=user_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.USER.value,
            entity_id=user.id,
            description=f"Создан сотрудник {user.full_name}",
        )
        db.session.commit()
        return user

    @classmethod
    def update_employee(cls, user: User, payload: EmployeePayload, actor_id: uuid.UUID) -> User:
        actor = cls._actor(actor_id)
        email = (payload.email or user.email or "").lower().strip()
        full_name = (payload.full_name or user.full_name or "").strip()
        if not email:
            raise ValidationError("Email обязателен.")
        if not full_name:
            raise ValidationError("ФИО обязательно.")
        cls._assert_privileged_changes(
            actor, target=user, role_ids=payload.role_ids, password=payload.password
        )
        if email != user.email:
            existing = db.session.scalar(
                db.select(User).where(User.email == email, User.active_filter(), User.id != user.id)
            )
            if existing is not None:
                raise ValidationError("Сотрудник с таким email уже существует.")

        user.email = email
        user.full_name = full_name
        user.phone = cls._normalize(payload.phone)
        user.position_id = payload.position_id
        user.department = cls._normalize(payload.department)
        cls._sync_position_label(user)
        user.updated_by = actor_id

        if payload.password:
            user.set_password(payload.password)

        cls._sync_roles(user, payload.role_ids)

        AuditService.log(
            user_id=actor_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.USER.value,
            entity_id=user.id,
            description=f"Обновлён сотрудник {user.full_name}",
        )
        db.session.commit()
        return user

    @classmethod
    def delete_employee(cls, user: User, actor_id: uuid.UUID) -> None:
        actor = cls._actor(actor_id)
        if user.id == actor_id:
            raise ValidationError("Нельзя удалить собственную учётную запись.")
        if user.is_admin and not actor.is_admin:
            raise ValidationError("Удалять администратора может только администратор.")
        name = user.full_name
        user.soft_delete(deleted_by=actor_id)
        AuditService.log(
            user_id=actor_id,
            action=AuditAction.SOFT_DELETE.value,
            entity_type=EntityType.USER.value,
            entity_id=user.id,
            description=f"Удалён сотрудник {name}",
        )
        db.session.commit()
