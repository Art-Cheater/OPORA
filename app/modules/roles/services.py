"""Сервисы модуля ролей."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import update

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.auth.associations import RolePermission
from app.models.auth.role import Role
from app.models.auth.role_field_permission import (
    FIELD_ACCESS_NONE,
    RoleFieldPermission,
)
from app.models.base import utcnow
from app.models.enums import AuditAction, EntityType
from app.modules.roles.repositories import RoleRepository


@dataclass
class FieldRulePayload:
    module: str
    field_name: str
    access_level: int


@dataclass
class RolePayload:
    code: str
    name: str
    description: str | None
    permission_ids: list[uuid.UUID]
    field_rules: list[FieldRulePayload]


class RoleService:
    @staticmethod
    def _sync_permissions(role: Role, permission_ids: list[uuid.UUID]) -> None:
        desired = set(permission_ids)
        rows = db.session.execute(
            db.select(RolePermission.id, RolePermission.permission_id).where(
                RolePermission.role_id == role.id,
                RolePermission.deleted_at.is_(None),
            )
        ).all()
        active = {perm_id: row_id for row_id, perm_id in rows if perm_id is not None}

        now = utcnow()
        remove_ids = [row_id for perm_id, row_id in active.items() if perm_id not in desired]
        if remove_ids:
            db.session.execute(
                update(RolePermission)
                .where(RolePermission.id.in_(remove_ids))
                .values(deleted_at=now, updated_at=now)
            )

        to_add = [
            RolePermission(role_id=role.id, permission_id=perm_id)
            for perm_id in desired
            if perm_id not in active
        ]
        if to_add:
            db.session.add_all(to_add)

    @staticmethod
    def _sync_field_rules(role: Role, rules: list[FieldRulePayload]) -> None:
        desired = {
            (rule.module, rule.field_name): rule.access_level
            for rule in rules
            if rule.access_level > FIELD_ACCESS_NONE
        }
        rows = list(
            db.session.scalars(
                db.select(RoleFieldPermission).where(
                    RoleFieldPermission.role_id == role.id,
                    RoleFieldPermission.deleted_at.is_(None),
                )
            )
        )
        active = {(row.module, row.field_name): row for row in rows}

        now = utcnow()
        remove_ids = [row.id for key, row in active.items() if key not in desired]
        if remove_ids:
            db.session.execute(
                update(RoleFieldPermission)
                .where(RoleFieldPermission.id.in_(remove_ids))
                .values(deleted_at=now, updated_at=now)
            )

        to_add: list[RoleFieldPermission] = []
        for key, level in desired.items():
            current = active.get(key)
            if current is not None:
                if current.access_level != level:
                    current.apply_level(level)
                    current.updated_at = now
                continue
            item = RoleFieldPermission(
                role_id=role.id,
                module=key[0],
                field_name=key[1],
            )
            item.apply_level(level)
            to_add.append(item)
        if to_add:
            db.session.add_all(to_add)

    @classmethod
    def create_role(cls, payload: RolePayload, actor_id: uuid.UUID) -> Role:
        if RoleRepository.get_by_code(payload.code):
            raise ValidationError("Роль с таким кодом уже существует.")
        role = Role(
            code=payload.code.strip().lower(),
            name=payload.name.strip(),
            description=(payload.description or "").strip() or None,
            is_system=False,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.session.add(role)
        db.session.flush()
        cls._sync_permissions(role, payload.permission_ids)
        cls._sync_field_rules(role, payload.field_rules)
        AuditService.log(
            user_id=actor_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.ROLE.value,
            entity_id=role.id,
            description=f"Создана роль {role.name}",
        )
        db.session.commit()
        cls._clear_cache()
        return role

    @classmethod
    def update_role(cls, role: Role, payload: RolePayload, actor_id: uuid.UUID) -> Role:
        if not role.is_system and payload.code.strip().lower() != role.code:
            existing = RoleRepository.get_by_code(payload.code)
            if existing and existing.id != role.id:
                raise ValidationError("Роль с таким кодом уже существует.")
            role.code = payload.code.strip().lower()
        role.name = payload.name.strip()
        role.description = (payload.description or "").strip() or None
        role.updated_by = actor_id
        cls._sync_permissions(role, payload.permission_ids)
        cls._sync_field_rules(role, payload.field_rules)
        AuditService.log(
            user_id=actor_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.ROLE.value,
            entity_id=role.id,
            description=f"Обновлена роль {role.name}",
        )
        db.session.commit()
        db.session.expire(role, ["role_permissions", "field_permissions"])
        cls._clear_cache()
        return role

    @classmethod
    def duplicate_role(cls, role: Role, actor_id: uuid.UUID) -> Role:
        base_code = f"{role.code}_copy"
        code = base_code
        suffix = 1
        while RoleRepository.get_by_code(code):
            suffix += 1
            code = f"{base_code}_{suffix}"

        perm_ids = RoleRepository.get_permission_ids(role)
        field_rules = [
            FieldRulePayload(
                module=rule.module,
                field_name=rule.field_name,
                access_level=rule.access_level,
            )
            for rule in RoleRepository.get_field_rules(role)
        ]
        payload = RolePayload(
            code=code,
            name=f"{role.name} (копия)",
            description=role.description,
            permission_ids=perm_ids,
            field_rules=field_rules,
        )
        return cls.create_role(payload, actor_id)

    @classmethod
    def delete_role(cls, role: Role, actor_id: uuid.UUID) -> None:
        if role.is_system:
            raise ValidationError("Системную роль нельзя удалить.")
        if RoleRepository.users_count(role) > 0:
            raise ValidationError("Нельзя удалить роль, назначенную сотрудникам.")
        name = role.name
        role.soft_delete(deleted_by=actor_id)
        AuditService.log(
            user_id=actor_id,
            action=AuditAction.SOFT_DELETE.value,
            entity_type=EntityType.ROLE.value,
            entity_id=role.id,
            description=f"Удалена роль {name}",
        )
        db.session.commit()
        cls._clear_cache()

    @staticmethod
    def _clear_cache() -> None:
        try:
            from app.core.permission_service import PermissionService

            PermissionService.clear_cache()
        except Exception:
            pass
