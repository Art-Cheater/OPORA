"""Сервисы модуля объектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.enums import AuditAction, EntityType, WorkObjectStatus
from app.models.work_objects.work_object import WorkObject


@dataclass
class ObjectPayload:
    name: str
    address: str | None
    plan_year: int | None
    notes: str | None
    status: str


class ObjectService:
    @staticmethod
    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @classmethod
    def create(cls, payload: ObjectPayload, user_id: uuid.UUID) -> WorkObject:
        if not payload.name.strip():
            raise ValidationError("Наименование объекта обязательно.")
        obj = WorkObject(
            name=payload.name.strip(),
            address=cls._normalize(payload.address),
            plan_year=payload.plan_year,
            notes=cls._normalize(payload.notes),
            status=payload.status or WorkObjectStatus.FREE.value,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(obj)
        db.session.flush()
        AuditService.log(
            user_id=user_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Создан объект {obj.name}",
            new_values={"name": obj.name, "status": obj.status},
        )
        db.session.commit()
        return obj

    @classmethod
    def update(cls, obj: WorkObject, payload: ObjectPayload, user_id: uuid.UUID) -> WorkObject:
        if not payload.name.strip():
            raise ValidationError("Наименование объекта обязательно.")
        old = {"name": obj.name, "status": obj.status, "address": obj.address}
        obj.name = payload.name.strip()
        obj.address = cls._normalize(payload.address)
        obj.plan_year = payload.plan_year
        obj.notes = cls._normalize(payload.notes)
        obj.status = payload.status
        obj.updated_by = user_id
        AuditService.log(
            user_id=user_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Обновлён объект {obj.name}",
            old_values=old,
            new_values={"name": obj.name, "status": obj.status, "address": obj.address},
        )
        db.session.commit()
        return obj

    @classmethod
    def soft_delete(cls, obj: WorkObject, user_id: uuid.UUID) -> None:
        if obj.status not in (WorkObjectStatus.FREE.value, WorkObjectStatus.ARCHIVED.value):
            raise ValidationError("Можно удалить только свободный или архивный объект.")
        obj.soft_delete(user_id)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.SOFT_DELETE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Удалён объект {obj.name}",
        )
        db.session.commit()
