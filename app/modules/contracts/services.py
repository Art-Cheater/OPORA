"""Сервисы модуля контрактов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
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

    @staticmethod
    def _snapshot(contract: Contract) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field in ContractService.TRACKED_FIELDS:
            value = getattr(contract, field)
            if isinstance(value, uuid.UUID):
                data[field] = str(value)
            elif isinstance(value, date):
                data[field] = value.isoformat()
            else:
                data[field] = value
        return data

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
            old_values=old_values,
            new_values=new_values,
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
                details=details,
                changed_by=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    @classmethod
    def create_contract(cls, payload: ContractPayload, user_id: uuid.UUID) -> Contract:
        cls.validate_payload(payload)
        exists = db.session.scalar(
            db.select(Contract).where(
                Contract.number == payload.number.strip(),
                Contract.active_filter(),
            )
        )
        if exists is not None:
            raise ValidationError("Контракт с таким номером уже существует.")

        contract = Contract(
            contract_type=payload.contract_type,
            number=payload.number.strip(),
            title=payload.title.strip(),
            description=cls._normalize_text(payload.description),
            status=payload.status,
            contract_date=payload.contract_date,
            responsible_id=payload.responsible_id,
            contractor_name=(payload.contractor_name or "").strip(),
            amount=payload.amount or 0,
            tender_application_id=payload.tender_application_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(contract)
        db.session.flush()

        snapshot = cls._snapshot(contract)
        cls._log_audit(user_id, AuditAction.CREATE.value, contract.id, f"Создан контракт {contract.number}", None, snapshot)
        cls._log_history(contract, user_id, "create", "Контракт создан", {"created": snapshot})
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
    ) -> ContractDocument:
        if not title.strip():
            raise ValidationError("Название документа обязательно.")

        document = ContractDocument(
            contract_id=contract.id,
            title=title.strip(),
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
        db.session.commit()
        return document

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
