"""Сервис дефектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from flask import request
from werkzeug.datastructures import FileStorage

from app.core.audit_service import AuditService
from app.core.exceptions import NotFoundError, ValidationError
from app.core.upload_utils import save_upload
from app.extensions import db
from app.models.communication.comment import Comment
from app.models.defects.defect import Defect
from app.models.defects.defect_history import DefectHistory
from app.models.enums import AuditAction, EntityType
from app.models.files.attachment import Attachment
from app.modules.defects.repositories import DefectRepository
from app.modules.defects.workflow import STATUS_FIXED, STATUS_OPEN, can_transition
from app.modules.requests.services import RequestService


@dataclass
class DefectPayload:
    number: str
    description: str
    category_id: uuid.UUID
    address: str
    original_address: str | None
    normalized_address: str | None
    region: str | None
    district: str | None
    settlement: str | None
    street: str | None
    house: str | None
    address_source: str | None
    address_external_id: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    responsible_id: uuid.UUID | None


class DefectService:
    TRACKED_FIELDS = [
        "number",
        "description",
        "category_id",
        "address",
        "district",
        "responsible_id",
        "status_id",
    ]

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
    def _log_audit(cls, user_id, action, entity_id, description, old_values=None, new_values=None):
        AuditService.log(
            user_id=user_id,
            action=action,
            entity_type=EntityType.DEFECT.value,
            entity_id=entity_id,
            description=description,
            old_values=old_values,
            new_values=new_values,
            ip_address=cls._client_ip(),
            user_agent=cls._user_agent(),
        )

    @staticmethod
    def _log_history(defect: Defect, user_id, action: str, comment: str | None = None, details=None, previous_status_id=None):
        db.session.add(
            DefectHistory(
                defect_id=defect.id,
                status_id=defect.status_id,
                previous_status_id=previous_status_id,
                action=action,
                comment=comment,
                details=details,
                changed_by=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    @staticmethod
    def _snapshot(item: Defect) -> dict[str, Any]:
        return {
            "number": item.number,
            "description": item.description,
            "address": item.address,
            "district": item.district,
            "status_id": str(item.status_id),
            "category_id": str(item.category_id),
            "responsible_id": str(item.responsible_id) if item.responsible_id else None,
        }

    @classmethod
    def validate_payload(cls, payload: DefectPayload) -> None:
        if not payload.number.strip():
            raise ValidationError("Номер дефекта обязателен.")
        if not (payload.description or "").strip():
            raise ValidationError("Описание обязательно.")
        if not (payload.address or "").strip():
            raise ValidationError("Адрес обязателен.")
        RequestService._prepare_address(payload)
        if payload.category_id is None:
            raise ValidationError("Укажите категорию дефекта.")

    @classmethod
    def create(cls, payload: DefectPayload, user_id: uuid.UUID) -> Defect:
        cls.validate_payload(payload)
        exists = db.session.scalar(
            db.select(Defect.id).where(Defect.number == payload.number.strip()).limit(1)
        )
        if exists is not None:
            raise ValidationError("Дефект с таким номером уже существует.")
        status = DefectRepository.get_status_by_code(STATUS_OPEN)
        if status is None:
            raise ValidationError("Статус «Открыт» не найден.")
        item = Defect(
            number=payload.number.strip(),
            description=payload.description.strip(),
            address=payload.address,
            original_address=payload.original_address,
            normalized_address=payload.normalized_address,
            region=payload.region,
            district=payload.district,
            settlement=payload.settlement,
            street=payload.street,
            house=payload.house,
            address_source=payload.address_source,
            address_external_id=payload.address_external_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            category_id=payload.category_id,
            responsible_id=payload.responsible_id,
            status_id=status.id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(item)
        try:
            db.session.flush()
        except IntegrityError as exc:
            db.session.rollback()
            raise ValidationError("Дефект с таким номером уже существует.") from exc
        cls._log_audit(user_id, AuditAction.CREATE.value, item.id, f"Создан дефект {item.number}", None, cls._snapshot(item))
        cls._log_history(item, user_id, "create", "Создан дефект")
        db.session.commit()
        return item

    @classmethod
    def update(cls, item: Defect, payload: DefectPayload, user_id: uuid.UUID) -> Defect:
        cls.validate_payload(payload)
        old = cls._snapshot(item)
        item.number = payload.number.strip()
        item.description = payload.description.strip()
        item.address = payload.address
        item.original_address = payload.original_address
        item.normalized_address = payload.normalized_address
        item.region = payload.region
        item.district = payload.district
        item.settlement = payload.settlement
        item.street = payload.street
        item.house = payload.house
        item.address_source = payload.address_source
        item.address_external_id = payload.address_external_id
        item.latitude = payload.latitude
        item.longitude = payload.longitude
        item.category_id = payload.category_id
        item.responsible_id = payload.responsible_id
        item.updated_by = user_id
        cls._log_audit(user_id, AuditAction.UPDATE.value, item.id, f"Изменён дефект {item.number}", old, cls._snapshot(item))
        cls._log_history(item, user_id, "update", "Изменение дефекта", {"old": old, "new": cls._snapshot(item)})
        db.session.commit()
        return item

    @classmethod
    def change_status(cls, item: Defect, status_code: str, user_id: uuid.UUID, comment: str | None = None) -> Defect:
        new_status = DefectRepository.get_status_by_code(status_code)
        if new_status is None:
            raise ValidationError("Статус не найден.")
        current = item.status.code if item.status else ""
        if not can_transition(current, status_code):
            raise ValidationError("Недопустимый переход статуса.")
        previous_id = item.status_id
        item.status_id = new_status.id
        item.updated_by = user_id
        cls._log_audit(
            user_id,
            AuditAction.STATUS_CHANGE.value,
            item.id,
            f"Статус дефекта {item.number}: {current} → {status_code}",
            {"status": current},
            {"status": status_code},
        )
        cls._log_history(item, user_id, "status_change", comment, {"from": current, "to": status_code}, previous_id)
        db.session.commit()
        return item

    @classmethod
    def mark_fixed_in_session(cls, item: Defect, user_id: uuid.UUID, *, comment: str | None = None) -> bool:
        """Закрывает дефект без commit. Для завершения путевого листа."""
        current = item.status.code if item.status else ""
        if not can_transition(current, STATUS_FIXED):
            return False
        new_status = DefectRepository.get_status_by_code(STATUS_FIXED)
        if new_status is None:
            return False
        previous_id = item.status_id
        item.status_id = new_status.id
        item.updated_by = user_id
        cls._log_audit(
            user_id,
            AuditAction.STATUS_CHANGE.value,
            item.id,
            f"Статус дефекта {item.number}: {current} → {STATUS_FIXED}",
            {"status": current},
            {"status": STATUS_FIXED},
        )
        cls._log_history(
            item,
            user_id,
            "status_change",
            comment,
            {"from": current, "to": STATUS_FIXED},
            previous_id,
        )
        return True

    @classmethod
    def delete(cls, item: Defect, user_id: uuid.UUID) -> None:
        number = item.number
        item.soft_delete(deleted_by=user_id)
        cls._log_audit(user_id, AuditAction.SOFT_DELETE.value, item.id, f"Удалён дефект {number}")
        db.session.commit()

    @classmethod
    def add_comment(cls, item: Defect, body: str, user_id: uuid.UUID) -> Comment:
        comment = Comment(
            author_id=user_id,
            entity_type=EntityType.DEFECT.value,
            entity_id=item.id,
            body=body.strip(),
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(comment)
        cls._log_audit(user_id, AuditAction.UPDATE.value, item.id, f"Комментарий к дефекту {item.number}")
        cls._log_history(item, user_id, "comment", body.strip()[:200])
        db.session.commit()
        return comment

    @classmethod
    def add_attachments(cls, item: Defect, files: list[FileStorage], user_id: uuid.UUID) -> list[Attachment]:
        saved: list[Attachment] = []
        for storage in files:
            if not storage or not storage.filename:
                continue
            uploaded = save_upload(storage, relative_dir=f"defects/{item.id}")
            att = Attachment(
                uploaded_by=user_id,
                entity_type=EntityType.DEFECT.value,
                entity_id=item.id,
                file_name=uploaded.file_name,
                storage_key=uploaded.storage_key,
                mime_type=uploaded.mime_type,
                file_size=uploaded.file_size,
                created_by=user_id,
                updated_by=user_id,
            )
            db.session.add(att)
            saved.append(att)
        if not saved:
            raise ValidationError("Выберите хотя бы один файл.")
        cls._log_audit(user_id, AuditAction.UPDATE.value, item.id, f"Файлы к дефекту {item.number}")
        cls._log_history(item, user_id, "attachment", f"Загружено файлов: {len(saved)}")
        db.session.commit()
        return saved

    @classmethod
    def delete_attachment(cls, item: Defect, attachment: Attachment, user_id: uuid.UUID) -> None:
        if attachment.entity_type != EntityType.DEFECT.value or attachment.entity_id != item.id:
            raise NotFoundError("Файл не найден.")
        attachment.soft_delete(deleted_by=user_id)
        cls._log_audit(user_id, AuditAction.SOFT_DELETE.value, item.id, f"Удалён файл дефекта {item.number}")
        cls._log_history(item, user_id, "attachment_delete", attachment.file_name)
        db.session.commit()
