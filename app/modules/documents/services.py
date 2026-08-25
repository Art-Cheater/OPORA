"""Личные файлы и договоры сотрудника."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from flask import current_app, url_for
from werkzeug.datastructures import FileStorage

from app.core.exceptions import NotFoundError, ValidationError
from app.core.upload_utils import UploadValidationError, save_upload
from app.extensions import db
from app.models.auth.user import User
from app.models.base import utcnow
from app.models.communication.notification import Notification
from app.models.documents.personal_contract import PersonalContract
from app.models.enums import EntityType, NotificationType
from app.models.files.attachment import Attachment
from app.modules.documents.parse_contract import parse_personal_contract_file

ENTITY_TYPE = EntityType.PERSONAL_DOCUMENT.value
CONTRACT_ENTITY = EntityType.PERSONAL_CONTRACT.value


class PersonalDocumentService:
    @staticmethod
    def list_for(user_id: uuid.UUID) -> list[Attachment]:
        contract_ids = db.session.scalars(
            db.select(PersonalContract.attachment_id).where(
                PersonalContract.user_id == user_id,
                PersonalContract.active_filter(),
            )
        ).all()
        stmt = (
            db.select(Attachment)
            .where(
                Attachment.entity_type == ENTITY_TYPE,
                Attachment.entity_id == user_id,
                Attachment.active_filter(),
            )
            .order_by(Attachment.created_at.desc())
        )
        rows = list(db.session.scalars(stmt))
        if not contract_ids:
            return rows
        skip = set(contract_ids)
        return [row for row in rows if row.id not in skip]

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
        contract = db.session.scalar(
            db.select(PersonalContract).where(
                PersonalContract.attachment_id == file_id,
                PersonalContract.user_id == user_id,
                PersonalContract.active_filter(),
            )
        )
        if contract is not None:
            contract.soft_delete(deleted_by=user_id)
        item.soft_delete(deleted_by=user_id)
        db.session.commit()

    @staticmethod
    def disk_path(item: Attachment) -> Path:
        return Path(current_app.config["UPLOAD_FOLDER"]) / item.storage_key

    @staticmethod
    def set_contracts_enabled(user: User, enabled: bool) -> None:
        user.personal_contracts_enabled = bool(enabled)
        user.updated_by = user.id
        db.session.commit()


class PersonalContractService:
    @staticmethod
    def list_for(user_id: uuid.UUID) -> list[PersonalContract]:
        return list(
            db.session.scalars(
                db.select(PersonalContract)
                .where(
                    PersonalContract.user_id == user_id,
                    PersonalContract.active_filter(),
                )
                .order_by(
                    PersonalContract.ends_on.asc().nullslast(),
                    PersonalContract.created_at.desc(),
                )
            )
        )

    @staticmethod
    def get_own(user_id: uuid.UUID, contract_id: uuid.UUID) -> PersonalContract | None:
        return db.session.scalar(
            db.select(PersonalContract).where(
                PersonalContract.id == contract_id,
                PersonalContract.user_id == user_id,
                PersonalContract.active_filter(),
            )
        )

    @classmethod
    def add_from_files(cls, user_id: uuid.UUID, files: list[FileStorage]) -> tuple[int, list[str]]:
        if not files:
            raise ValidationError("Выберите хотя бы один файл договора.")
        saved = 0
        notes: list[str] = []
        for file_storage in files:
            try:
                stored = save_upload(file_storage, relative_dir=f"personal/{user_id}/contracts")
            except UploadValidationError as exc:
                raise ValidationError(str(exc)) from exc
            attachment = Attachment(
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
            db.session.add(attachment)
            db.session.flush()
            path = Path(current_app.config["UPLOAD_FOLDER"]) / stored.storage_key
            parsed = parse_personal_contract_file(path, stored.file_name)
            db.session.add(
                PersonalContract(
                    user_id=user_id,
                    attachment_id=attachment.id,
                    title=parsed.title,
                    description=parsed.description,
                    ends_on=parsed.ends_on,
                    reminders_enabled=True,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            saved += 1
            if parsed.warnings:
                notes.append(f"{stored.file_name}: {'; '.join(parsed.warnings)}")
        db.session.commit()
        return saved, notes

    @classmethod
    def update(
        cls,
        user_id: uuid.UUID,
        contract_id: uuid.UUID,
        *,
        title: str,
        description: str | None,
        ends_on: date | None,
        reminders_enabled: bool,
    ) -> PersonalContract:
        item = cls.get_own(user_id, contract_id)
        if item is None:
            raise NotFoundError("Договор не найден.")
        title = (title or "").strip()
        if not title:
            raise ValidationError("Укажите название договора.")
        item.title = title[:500]
        item.description = (description or "").strip()[:2000] or None
        item.ends_on = ends_on
        item.reminders_enabled = bool(reminders_enabled)
        item.updated_by = user_id
        # если дату поменяли — можно снова напомнить
        item.reminded_month_at = None
        item.reminded_two_weeks_at = None
        db.session.commit()
        return item

    @classmethod
    def delete(cls, user_id: uuid.UUID, contract_id: uuid.UUID) -> None:
        item = cls.get_own(user_id, contract_id)
        if item is None:
            raise NotFoundError("Договор не найден.")
        attachment = db.session.get(Attachment, item.attachment_id)
        item.soft_delete(deleted_by=user_id)
        if attachment is not None and attachment.deleted_at is None:
            attachment.soft_delete(deleted_by=user_id)
        db.session.commit()

    @classmethod
    def send_due_reminders(cls) -> dict[str, int]:
        """Напоминания за месяц и за две недели до окончания."""
        today = date.today()
        sent_month = 0
        sent_two_weeks = 0

        contracts = list(
            db.session.scalars(
                db.select(PersonalContract).where(
                    PersonalContract.active_filter(),
                    PersonalContract.reminders_enabled.is_(True),
                    PersonalContract.ends_on.is_not(None),
                )
            )
        )
        for contract in contracts:
            user = db.session.get(User, contract.user_id)
            if user is None or not user.personal_contracts_enabled:
                continue
            ends = contract.ends_on
            if ends is None:
                continue
            days_left = (ends - today).days
            if days_left < 0:
                continue
            link = url_for("documents.index", tab="contracts", _external=False)
            ends_label = ends.strftime("%d.%m.%Y")

            if 14 < days_left <= 30 and contract.reminded_month_at is None:
                db.session.add(
                    Notification(
                        user_id=contract.user_id,
                        title="Договор заканчивается через месяц",
                        message=(
                            f"«{contract.title}» действует до {ends_label}. "
                            "Проверьте документы и продление."
                        ),
                        type=NotificationType.WARNING.value,
                        entity_type=CONTRACT_ENTITY,
                        entity_id=contract.id,
                        link=link,
                        created_by=contract.user_id,
                        updated_by=contract.user_id,
                    )
                )
                contract.reminded_month_at = utcnow()
                sent_month += 1

            if 0 <= days_left <= 14 and contract.reminded_two_weeks_at is None:
                db.session.add(
                    Notification(
                        user_id=contract.user_id,
                        title="Договор заканчивается через 2 недели",
                        message=(
                            f"«{contract.title}» действует до {ends_label}. "
                            "Осталось мало времени — уточните статус."
                        ),
                        type=NotificationType.WARNING.value,
                        entity_type=CONTRACT_ENTITY,
                        entity_id=contract.id,
                        link=link,
                        created_by=contract.user_id,
                        updated_by=contract.user_id,
                    )
                )
                contract.reminded_two_weeks_at = utcnow()
                sent_two_weeks += 1

        if sent_month or sent_two_weeks:
            db.session.commit()
        return {"month": sent_month, "two_weeks": sent_two_weeks}
