"""Личные файлы сотрудника: видны только владельцу."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.core.exceptions import NotFoundError, ValidationError
from app.core.upload_utils import UploadValidationError, save_upload
from app.extensions import db
from app.models.enums import EntityType
from app.models.files.attachment import Attachment

ENTITY_TYPE = EntityType.PERSONAL_DOCUMENT.value


class PersonalDocumentService:
    @staticmethod
    def list_for(user_id: uuid.UUID) -> list[Attachment]:
        return list(
            db.session.scalars(
                db.select(Attachment)
                .where(
                    Attachment.entity_type == ENTITY_TYPE,
                    Attachment.entity_id == user_id,
                    Attachment.active_filter(),
                )
                .order_by(Attachment.created_at.desc())
            )
        )

    @staticmethod
    def get_own(user_id: uuid.UUID, file_id: uuid.UUID) -> Attachment | None:
        return db.session.scalar(
            db.select(Attachment).where(
                Attachment.id == file_id,
                Attachment.entity_type == ENTITY_TYPE,
                Attachment.entity_id == user_id,
                Attachment.active_filter(),
            )
        )

    @classmethod
    def add_files(cls, user_id: uuid.UUID, files: list[FileStorage]) -> int:
        if not files:
            raise ValidationError("Выберите хотя бы один файл.")
        saved = 0
        for file_storage in files:
            try:
                stored = save_upload(file_storage, relative_dir=f"personal/{user_id}")
            except UploadValidationError as exc:
                raise ValidationError(str(exc)) from exc
            db.session.add(
                Attachment(
                    uploaded_by=user_id,
                    entity_type=ENTITY_TYPE,
                    entity_id=user_id,
                    file_name=stored.file_name,
                    mime_type=stored.mime_type,
                    file_size=stored.file_size,
                    storage_key=stored.storage_key,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            saved += 1
        db.session.commit()
        return saved

    @classmethod
    def delete(cls, user_id: uuid.UUID, file_id: uuid.UUID) -> None:
        item = cls.get_own(user_id, file_id)
        if item is None:
            raise NotFoundError("Файл не найден.")
        item.soft_delete(deleted_by=user_id)
        db.session.commit()

    @staticmethod
    def disk_path(item: Attachment) -> Path:
        return Path(current_app.config["UPLOAD_FOLDER"]) / item.storage_key
