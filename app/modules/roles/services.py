"""Сервисы модуля ролей."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.auth.associations import RolePermission
from app.models.auth.role import Role
from app.models.auth.role_field_permission import (
    FIELD_ACCESS_NONE,
    RoleFieldPermission,
)
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
        active = {
            rp.permission_id: rp
            for rp in role.role_permissions
            if rp.deleted_at is None and rp.permission_id is not None
        }
        for perm_id, rp in list(active.items()):
            if perm_id not in desired:
                rp.soft_delete()
        for perm_id in desired:
            if perm_id not in active:
                db.session.add(RolePermission(role_id=role.id, permission_id=perm_id))

    @staticmethod
    def _sync_field_rules(role: Role, rules: list[FieldRulePayload]) -> None:
        for fp in list(role.field_permissions):
            if fp.deleted_at is None:
                fp.soft_delete()
        for rule in rules:
            if rule.access_level <= FIELD_ACCESS_NONE:
                continue
            rfp = RoleFieldPermission(
                role_id=role.id,
                module=rule.module,
                field_name=rule.field_name,
            )
            rfp.apply_level(rule.access_level)
            db.session.add(rfp)

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
