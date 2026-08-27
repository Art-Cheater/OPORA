"""Сервисы модуля контрактов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from flask import request

from app.core.audit_service import AuditService
from app.core.exceptions import NotFoundError, ValidationError
from app.extensions import db
from app.models.communication.comment import Comment
from app.models.contracts.contract import Contract
from app.models.contracts.contract_document import ContractDocument
from app.models.contracts.contract_history import ContractHistory
from app.models.contracts.contract_object import ContractObject
from app.models.enums import (
    AuditAction,
    ContractDocumentType,
    ContractStatus,
    ContractType,
    EntityType,
    ProjectStatus,
    TenderApplicationStatus,
    WorkObjectStatus,
)
from app.models.projects.project import Project
from app.models.tenders.tender_application import TenderApplication
from app.models.work_objects.work_object import WorkObject


CONTRACT_TRANSITIONS: dict[str, set[str]] = {
    ContractStatus.DRAFT.value: {ContractStatus.ACTIVE.value, ContractStatus.TERMINATED.value},
    ContractStatus.ACTIVE.value: {
        ContractStatus.WORK_DOCS_PENDING.value,
        ContractStatus.TERMINATED.value,
    },
    ContractStatus.WORK_DOCS_PENDING.value: {
        ContractStatus.IN_PROGRESS.value,
        ContractStatus.TERMINATED.value,
    },
    ContractStatus.IN_PROGRESS.value: {
        ContractStatus.KS2_PENDING.value,
        ContractStatus.TERMINATED.value,
    },
    ContractStatus.KS2_PENDING.value: {
        ContractStatus.COMPLETED.value,
        ContractStatus.REJECTED.value,
        ContractStatus.TERMINATED.value,
    },
    ContractStatus.REJECTED.value: {
        ContractStatus.KS2_PENDING.value,
        ContractStatus.TERMINATED.value,
    },
    ContractStatus.COMPLETED.value: set(),
    ContractStatus.TERMINATED.value: set(),
}


@dataclass
class ContractPayload:
    contract_type: str
    number: str
    title: str
    description: str | None
    status: str
    contract_date: date | None
    end_date: date | None
    responsible_id: uuid.UUID | None
    contractor_name: str = ""
    amount: Any = 0
    tender_application_id: uuid.UUID | None = None


class ContractService:
    """CRUD + аудит + история изменений контрактов."""

    TRACKED_FIELDS = [
        "contract_type",
        "number",
        "title",
        "description",
        "status",
        "contract_date",
        "end_date",
        "responsible_id",
        "contractor_name",
        "amount",
        "tender_application_id",
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

    @staticmethod
    def _normalize_text(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @classmethod
    def validate_payload(cls, payload: ContractPayload) -> None:
        if not payload.number.strip():
            raise ValidationError("Номер контракта обязателен.")
        if not payload.title.strip():
            raise ValidationError("Название контракта обязательно.")
        if not (payload.contractor_name or "").strip():
            raise ValidationError("Укажите подрядчика.")
        try:
            amount = Decimal(str(payload.amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError("Введите корректную сумму контракта.") from exc
        if not amount.is_finite() or amount <= 0:
            raise ValidationError("Сумма контракта должна быть больше нуля.")
        if not isinstance(payload.end_date, date):
            raise ValidationError("Укажите дату окончания контракта.")
        payload.amount = amount

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Преобразовать значения ORM в типы, поддерживаемые JSON/JSONB."""
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Enum):
            return ContractService._json_safe(value.value)
        if isinstance(value, dict):
            return {str(key): ContractService._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ContractService._json_safe(item) for item in value]
        return value

    @staticmethod
    def _snapshot(contract: Contract) -> dict[str, Any]:
        return {
            field: ContractService._json_safe(getattr(contract, field))
            for field in ContractService.TRACKED_FIELDS
        }

    @staticmethod
    def _diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
        changes: dict[str, dict[str, Any]] = {}
        for key in set(old.keys()) | set(new.keys()):
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}
        return changes

    @classmethod
    def _log_audit(
        cls,
        user_id: uuid.UUID,
        action: str,
        entity_id: uuid.UUID,
        description: str,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
    ) -> None:
        AuditService.log(
            user_id=user_id,
            action=action,
            entity_type=EntityType.CONTRACT.value,
            entity_id=entity_id,
            description=description,
            old_values=cls._json_safe(old_values),
            new_values=cls._json_safe(new_values),
        )

    @staticmethod
    def _log_history(
        contract: Contract,
        user_id: uuid.UUID,
        action: str,
        comment: str | None,
        details: dict[str, Any] | None,
        previous_status: str | None = None,
    ) -> None:
        db.session.add(
            ContractHistory(
                contract_id=contract.id,
                status=contract.status,
                previous_status=previous_status,
                action=action,
                comment=comment,
                details=ContractService._json_safe(details),
                changed_by=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    @classmethod
    def create_contract(
        cls,
        payload: ContractPayload,
        user_id: uuid.UUID,
        *,
        object_id: uuid.UUID | None = None,
    ) -> Contract:
        cls.validate_payload(payload)
        exists = db.session.scalar(
            db.select(Contract).where(
                Contract.number == payload.number.strip(),
                Contract.active_filter(),
            )
        )
        if exists is not None:
            raise ValidationError("Контракт с таким номером уже существует.")

        work_object = None
        if object_id is not None:
            work_object = db.session.scalar(
                db.select(WorkObject).where(WorkObject.id == object_id, WorkObject.active_filter())
            )
            if work_object is None:
                raise ValidationError("Объект не найден.")

        contract = Contract(
            contract_type=payload.contract_type,
            number=payload.number.strip(),
            title=payload.title.strip(),
            description=cls._normalize_text(payload.description),
            status=payload.status,
            contract_date=payload.contract_date,
            end_date=payload.end_date,
            responsible_id=payload.responsible_id,
            contractor_name=(payload.contractor_name or "").strip(),
            amount=payload.amount or 0,
            tender_application_id=payload.tender_application_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(contract)
        db.session.flush()

        if work_object is not None:
            db.session.add(
                ContractObject(
                    contract_id=contract.id,
                    object_id=work_object.id,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            work_object.status = WorkObjectStatus.IN_CONTRACT.value
            work_object.updated_by = user_id

        snapshot = cls._snapshot(contract)
        cls._log_audit(user_id, AuditAction.CREATE.value, contract.id, f"Создан контракт {contract.number}", None, snapshot)
        cls._log_history(contract, user_id, "create", "Контракт создан", {"created": snapshot})
        db.session.commit()
        return contract

    @classmethod
    def _ensure_object_link(cls, contract: Contract, work_object: WorkObject, user_id: uuid.UUID) -> None:
        existing = db.session.scalar(
            db.select(ContractObject).where(
                ContractObject.contract_id == contract.id,
                ContractObject.object_id == work_object.id,
            )
        )
        if existing is None:
            db.session.add(
                ContractObject(
                    contract_id=contract.id,
                    object_id=work_object.id,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
            return
        if existing.deleted_at is not None:
            existing.restore()
            existing.updated_by = user_id

    @classmethod
    def create_draft_from_plan(
        cls,
        obj: WorkObject,
        user_id: uuid.UUID,
        *,
        project: Project | None = None,
        tender: TenderApplication | None = None,
        commit: bool = False,
    ) -> Contract:
        """Черновик контракта по полям плана освещения. Сумма и срок могут быть пустыми."""
        from app.modules.tenders.services import TenderService

        number = (obj.contract_number or "").strip()
        if not number:
            raise ValidationError("Номер контракта обязателен.")

        existing = db.session.scalar(
            db.select(Contract).where(Contract.number == number, Contract.active_filter())
        )
        if existing is not None:
            cls._ensure_object_link(existing, obj, user_id)
            if project is not None and existing.project_id is None:
                existing.project_id = project.id
            if tender is not None and existing.tender_application_id is None:
                existing.tender_application_id = tender.id
            obj.status = WorkObjectStatus.IN_CONTRACT.value
            obj.updated_by = user_id
            if project is not None:
                project.status = ProjectStatus.IN_CONTRACT.value
                project.updated_by = user_id
            if commit:
                db.session.commit()
            return existing

        amount = obj.contract_amount
        if amount is None:
            amount = obj.budget_amount
        if amount is None:
            amount = Decimal("0")
        contractor = (obj.contractor_name or "").strip() or "Не указан"
        title = (obj.name or obj.display_address or number)[:500]
        contract = Contract(
            contract_type=ContractType.WORK.value,
            number=number[:100],
            title=title,
            description=cls._normalize_text(obj.result_text),
            status=ContractStatus.DRAFT.value,
            contract_date=obj.contract_date,
            start_date=obj.contract_date,
            end_date=TenderService.parse_deadline_date(obj.work_deadline),
            responsible_id=user_id,
            contractor_name=contractor[:500],
            amount=amount,
            tender_application_id=tender.id if tender is not None else None,
            project_id=project.id if project is not None else None,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(contract)
        db.session.flush()
        cls._ensure_object_link(contract, obj, user_id)
        obj.status = WorkObjectStatus.IN_CONTRACT.value
        obj.updated_by = user_id
        if project is not None:
            project.status = ProjectStatus.IN_CONTRACT.value
            project.updated_by = user_id
        snapshot = cls._snapshot(contract)
        cls._log_audit(
            user_id,
            AuditAction.CREATE.value,
            contract.id,
            f"Черновик контракта {contract.number} по объекту плана",
            None,
            snapshot,
        )
        cls._log_history(contract, user_id, "create", "Черновик контракта из плана", {"created": snapshot})
        if commit:
            db.session.commit()
        return contract

    @classmethod
    def create_from_tender(
        cls,
        tender: TenderApplication,
        payload: ContractPayload,
        user_id: uuid.UUID,
    ) -> Contract:
        if tender.status != TenderApplicationStatus.WON.value:
            raise ValidationError("Контракт можно создать только после победы на торгах.")
        existing = db.session.scalar(
            db.select(Contract).where(
                Contract.tender_application_id == tender.id,
                Contract.active_filter(),
                Contract.status.notin_([ContractStatus.TERMINATED.value]),
            )
        )
        if existing is not None:
            raise ValidationError("По этой заявке на торги уже есть активный контракт.")

        payload.tender_application_id = tender.id
        if not payload.status:
            payload.status = ContractStatus.DRAFT.value
        cls.validate_payload(payload)

        projects = [
            link.project
            for link in tender.project_links
            if link.deleted_at is None and link.project is not None
        ]
        if not projects:
            raise ValidationError("В заявке на торги нет проектов.")

        first_project = projects[0]
        contract = Contract(
            contract_type=payload.contract_type,
            number=payload.number.strip(),
            title=payload.title.strip(),
            description=cls._normalize_text(payload.description),
            status=payload.status,
            contract_date=payload.contract_date,
            end_date=payload.end_date,
            responsible_id=payload.responsible_id,
            contractor_name=(payload.contractor_name or "").strip(),
            amount=payload.amount or 0,
            tender_application_id=tender.id,
            project_id=first_project.id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(contract)
        db.session.flush()

        for project in projects:
            if project.object_id:
                db.session.add(
                    ContractObject(
                        contract_id=contract.id,
                        object_id=project.object_id,
                        created_by=user_id,
                        updated_by=user_id,
                    )
                )
            project.status = ProjectStatus.IN_CONTRACT.value
            project.updated_by = user_id
            if project.work_object:
                project.work_object.status = WorkObjectStatus.IN_CONTRACT.value
                project.work_object.updated_by = user_id

        snapshot = cls._snapshot(contract)
        cls._log_audit(
            user_id,
            AuditAction.CREATE.value,
            contract.id,
            f"Контракт {contract.number} из заявки на торги {tender.number}",
            None,
            snapshot,
        )
        cls._log_history(contract, user_id, "create", "Контракт создан из заявки на торги", {"created": snapshot})
        db.session.commit()
        return contract

    @classmethod
    def update_contract(
        cls,
        contract: Contract,
        payload: ContractPayload,
        user_id: uuid.UUID,
    ) -> Contract:
        cls.validate_payload(payload)
        old_snapshot = cls._snapshot(contract)
        previous_status = contract.status

        contract.contract_type = payload.contract_type
        contract.number = payload.number.strip()
        contract.title = payload.title.strip()
        contract.description = cls._normalize_text(payload.description)
        contract.status = payload.status
        contract.contract_date = payload.contract_date
        contract.end_date = payload.end_date
        contract.responsible_id = payload.responsible_id
        contract.contractor_name = (payload.contractor_name or "").strip()
        contract.amount = payload.amount or 0
        contract.updated_by = user_id

        new_snapshot = cls._snapshot(contract)
        changes = cls._diff(old_snapshot, new_snapshot)
        if not changes:
            return contract

        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            contract.id,
            f"Обновлён контракт {contract.number}",
            old_snapshot,
            new_snapshot,
        )
        history_action = "status_change" if previous_status != contract.status else "update"
        cls._log_history(
            contract,
            user_id,
            history_action,
            "Обновление контракта",
            {"changes": changes},
            previous_status=previous_status,
        )
        db.session.commit()
        return contract

    @classmethod
    def transition(
        cls,
        contract: Contract,
        new_status: str,
        user_id: uuid.UUID,
        *,
        comment: str | None = None,
        require_rejection_memo: bool = False,
    ) -> Contract:
        allowed = CONTRACT_TRANSITIONS.get(contract.status, set())
        if new_status not in allowed:
            raise ValidationError(
                f"Переход из «{contract.status}» в «{new_status}» недоступен."
            )
        if require_rejection_memo:
            has_memo = any(
                d.deleted_at is None and d.document_type == ContractDocumentType.REJECTION_MEMO.value
                for d in contract.documents
            )
            if not has_memo:
                raise ValidationError("Для отклонения нужна служебная записка с замечаниями.")

        previous = contract.status
        contract.status = new_status
        contract.updated_by = user_id

        if new_status == ContractStatus.COMPLETED.value:
            for link in contract.object_links:
                if link.work_object:
                    link.work_object.status = WorkObjectStatus.COMPLETED.value
                    link.work_object.updated_by = user_id
            if contract.tender_application_id:
                for link in contract.tender_application.project_links if contract.tender_application else []:
                    if link.project:
                        link.project.status = ProjectStatus.COMPLETED.value
                        link.project.updated_by = user_id

        cls._log_audit(
            user_id,
            AuditAction.STATUS_CHANGE.value,
            contract.id,
            f"Статус контракта {contract.number}: {previous} → {new_status}",
        )
        cls._log_history(
            contract,
            user_id,
            "status_change",
            comment or "Смена статуса",
            {"from": previous, "to": new_status},
            previous_status=previous,
        )
        db.session.commit()
        return contract

    @classmethod
    def add_comment(cls, contract: Contract, body: str, user_id: uuid.UUID) -> Comment:
        body = body.strip()
        if not body:
            raise ValidationError("Комментарий не может быть пустым.")
        comment = Comment(
            author_id=user_id,
            entity_type=EntityType.CONTRACT.value,
            entity_id=contract.id,
            body=body,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(comment)
        cls._log_audit(user_id, AuditAction.UPDATE.value, contract.id, "Добавлен комментарий к контракту", None, {"comment": body})
        cls._log_history(contract, user_id, "comment", "Добавлен комментарий", {"comment": body})
        db.session.commit()
        return comment

    @classmethod
    def document_type_label(cls, document_type: str) -> str:
        from app.modules.contracts.forms import CONTRACT_DOC_TYPE_LABELS

        return CONTRACT_DOC_TYPE_LABELS.get(document_type, "Документ")

    @staticmethod
    def _title_from_filename(file_name: str | None) -> str:
        raw = (file_name or "").strip()
        stem = raw.rsplit(".", 1)[0].strip() if raw else "файл"
        stem = stem.replace("_", " ").replace("-", " ").strip()
        return (stem or "файл")[:500]

    @classmethod
    def suggest_document_title(
        cls,
        *,
        document_type: str,
        file_name: str | None,
        user_title: str | None = None,
        for_batch: bool = False,
    ) -> str:
        manual = (user_title or "").strip()
        type_label = cls.document_type_label(document_type)
        if document_type == ContractDocumentType.OTHER.value:
            stem = cls._title_from_filename(file_name)
            if manual and for_batch:
                return f"{manual} — {stem}"[:500]
            if manual and not for_batch:
                return manual[:500]
            return stem
        if manual:
            return manual[:500]
        return type_label[:500]

    @classmethod
    def add_documents_from_uploads(
        cls,
        contract: Contract,
        *,
        document_type: str,
        title: str | None,
        document_number: str | None,
        document_date: date | None,
        description: str | None,
        uploads: list,
        user_id: uuid.UUID,
    ) -> list[ContractDocument]:
        if not uploads:
            raise ValidationError("Выберите файл для загрузки.")
        from app.modules.contracts.forms import CONTRACT_DOC_TYPE_LABELS

        if document_type not in CONTRACT_DOC_TYPE_LABELS:
            raise ValidationError("Некорректный тип документа.")
        if document_type != ContractDocumentType.OTHER.value and len(uploads) > 1:
            raise ValidationError("Для выбранного типа документа можно загрузить только один файл.")

        created: list[ContractDocument] = []
        batch = len(uploads) > 1
        for item in uploads:
            file_name = getattr(item, "file_name", None)
            doc_title = cls.suggest_document_title(
                document_type=document_type,
                file_name=file_name,
                user_title=title,
                for_batch=batch,
            )
            created.append(
                cls.add_document(
                    contract,
                    title=doc_title,
                    document_type=document_type,
                    document_number=document_number,
                    document_date=document_date,
                    description=description,
                    file_name=file_name,
                    mime_type=getattr(item, "mime_type", None),
                    storage_key=getattr(item, "storage_key", None),
                    user_id=user_id,
                    commit=False,
                )
            )
        db.session.commit()
        return created

    @classmethod
    def add_document(
        cls,
        contract: Contract,
        *,
        title: str,
        document_number: str | None,
        document_date: date | None,
        description: str | None,
        file_name: str | None,
        mime_type: str | None,
        storage_key: str | None,
        user_id: uuid.UUID,
        document_type: str = ContractDocumentType.OTHER.value,
        commit: bool = True,
    ) -> ContractDocument:
        if not (title or "").strip():
            raise ValidationError("Название документа обязательно.")

        document = ContractDocument(
            contract_id=contract.id,
            title=title.strip()[:500],
            document_type=document_type or ContractDocumentType.OTHER.value,
            document_number=cls._normalize_text(document_number),
            document_date=document_date,
            description=cls._normalize_text(description),
            file_name=file_name,
            mime_type=mime_type,
            storage_key=storage_key,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(document)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            contract.id,
            f"Добавлен документ к контракту: {document.title}",
            None,
            {"document": {"title": document.title, "type": document.document_type}},
        )
        cls._log_history(
            contract,
            user_id,
            "document",
            "Добавлен документ",
            {"title": document.title, "type": document.document_type},
        )
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return document

    @classmethod
    def update_document(
        cls,
        document: ContractDocument,
        *,
        title: str,
        document_type: str,
        document_number: str | None,
        document_date: date | None,
        description: str | None,
        user_id: uuid.UUID,
    ) -> ContractDocument:
        if not (title or "").strip():
            raise ValidationError("Название документа обязательно.")
        from app.modules.contracts.forms import CONTRACT_DOC_TYPE_LABELS

        if document_type not in CONTRACT_DOC_TYPE_LABELS:
            raise ValidationError("Некорректный тип документа.")
        before = {
            "title": document.title,
            "document_type": document.document_type,
            "document_number": document.document_number,
            "document_date": document.document_date.isoformat() if document.document_date else None,
            "description": document.description,
        }
        document.title = title.strip()[:500]
        document.document_type = document_type
        document.document_number = cls._normalize_text(document_number)
        document.document_date = document_date
        document.description = cls._normalize_text(description)
        document.updated_by = user_id
        after = {
            "title": document.title,
            "document_type": document.document_type,
            "document_number": document.document_number,
            "document_date": document.document_date.isoformat() if document.document_date else None,
            "description": document.description,
        }
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            document.contract_id,
            f"Изменён документ контракта: {document.title}",
            before,
            after,
        )
        contract = db.session.get(Contract, document.contract_id)
        if contract is not None:
            cls._log_history(
                contract,
                user_id,
                "document_update",
                "Изменён документ",
                {"title": document.title, "document_id": str(document.id)},
            )
        db.session.commit()
        return document

    @classmethod
    def delete_document(cls, document: ContractDocument, user_id: uuid.UUID) -> None:
        title = document.title
        contract_id = document.contract_id
        document.soft_delete(deleted_by=user_id)
        cls._log_audit(
            user_id,
            AuditAction.SOFT_DELETE.value,
            contract_id,
            f"Удалён документ контракта: {title}",
            {"document": {"title": title, "id": str(document.id)}},
            None,
        )
        contract = db.session.get(Contract, contract_id)
        if contract is not None:
            cls._log_history(
                contract,
                user_id,
                "document_delete",
                "Удалён документ",
                {"title": title, "document_id": str(document.id)},
            )
        db.session.commit()

    @classmethod
    def link_object(
        cls, contract: Contract, work_object: WorkObject, user_id: uuid.UUID
    ) -> ContractObject:
        before = None
        existing = db.session.scalar(
            db.select(ContractObject).where(
                ContractObject.contract_id == contract.id,
                ContractObject.object_id == work_object.id,
            )
        )
        created = False
        if existing is None:
            existing = ContractObject(
                contract_id=contract.id,
                object_id=work_object.id,
                created_by=user_id,
                updated_by=user_id,
            )
            db.session.add(existing)
            created = True
        elif existing.deleted_at is not None:
            existing.restore()
            existing.updated_by = user_id
            created = True
        work_object.status = WorkObjectStatus.IN_CONTRACT.value
        work_object.updated_by = user_id
        if created:
            cls._log_audit(
                user_id,
                AuditAction.UPDATE.value,
                contract.id,
                f"Привязан объект к контракту: {work_object.display_address}",
                before,
                {"object_id": str(work_object.id)},
            )
            cls._log_history(
                contract,
                user_id,
                "object_link",
                "Привязан объект",
                {"object_id": str(work_object.id)},
            )
        db.session.commit()
        return existing

    @classmethod
    def unlink_object(
        cls, contract: Contract, work_object: WorkObject, user_id: uuid.UUID
    ) -> None:
        link = db.session.scalar(
            db.select(ContractObject).where(
                ContractObject.contract_id == contract.id,
                ContractObject.object_id == work_object.id,
                ContractObject.active_filter(),
            )
        )
        if link is None:
            raise ValidationError("Связь с объектом не найдена.")
        link.soft_delete(deleted_by=user_id)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            contract.id,
            f"Отвязан объект от контракта: {work_object.display_address}",
            {"object_id": str(work_object.id)},
            None,
        )
        cls._log_history(
            contract,
            user_id,
            "object_unlink",
            "Отвязан объект",
            {"object_id": str(work_object.id)},
        )
        db.session.commit()

    @classmethod
    def set_project(
        cls, contract: Contract, project: Project | None, user_id: uuid.UUID
    ) -> Contract:
        old = str(contract.project_id) if contract.project_id else None
        contract.project_id = project.id if project is not None else None
        contract.updated_by = user_id
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            contract.id,
            "Изменена связь контракта с проектом",
            {"project_id": old},
            {"project_id": str(project.id) if project else None},
        )
        db.session.commit()
        return contract

    @classmethod
    def delete_contract(cls, contract: Contract, user_id: uuid.UUID) -> None:
        number = contract.number
        contract.soft_delete(deleted_by=user_id)
        cls._log_audit(
            user_id,
            AuditAction.SOFT_DELETE.value,
            contract.id,
            f"Удалён контракт {number}",
        )
        db.session.commit()

    @staticmethod
    def ensure_contract(contract_id: str) -> Contract:
        contract = db.session.get(Contract, uuid.UUID(contract_id))
        if contract is None or contract.deleted_at is not None:
            raise NotFoundError("Контракт не найден.")
        return contract
