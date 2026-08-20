"""Сервис справочника подрядчиков."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.contractors.contractor import Contractor
from app.models.enums import AuditAction, EntityType
from app.modules.contractors.repositories import ContractorRepository


@dataclass
class ContractorPayload:
    name: str
    inn: str | None = None
    kpp: str | None = None
    kpp_largest: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None


class ContractorService:
    @staticmethod
    def _clean(value: str | None, size: int | None = None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if size:
            return text[:size]
        return text

    @classmethod
    def _digits(cls, value: str | None, size: int) -> str | None:
        text = cls._clean(value, size)
        if not text:
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits[:size] or None

    @classmethod
    def upsert_from_eis(
        cls,
        *,
        name: str,
        inn: str | None,
        kpp: str | None = None,
        kpp_largest: str | None = None,
        user_id: uuid.UUID | None,
    ) -> Contractor:
        inn_n = cls._digits(inn, 12)
        name_n = cls._clean(name, 500) or "Без названия"
        existing = ContractorRepository.get_by_inn(inn_n) if inn_n else None
        if existing is None and inn_n is None:
            existing = db.session.scalar(
                db.select(Contractor).where(
                    Contractor.name == name_n,
                    Contractor.active_filter(),
                )
            )
        if existing is not None:
            existing.name = name_n
            if kpp:
                existing.kpp = cls._digits(kpp, 9)
            if kpp_largest:
                existing.kpp_largest = cls._digits(kpp_largest, 9)
            existing.updated_by = user_id
            return existing
        contractor = Contractor(
            name=name_n,
            inn=inn_n,
            kpp=cls._digits(kpp, 9),
            kpp_largest=cls._digits(kpp_largest, 9),
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(contractor)
        db.session.flush()
        return contractor

    @classmethod
    def create(cls, payload: ContractorPayload, user_id: uuid.UUID) -> Contractor:
        name = cls._clean(payload.name, 500)
        if not name:
            raise ValidationError("Укажите наименование подрядчика.")
        inn = cls._digits(payload.inn, 12)
        if inn and ContractorRepository.get_by_inn(inn) is not None:
            raise ValidationError("Подрядчик с таким ИНН уже есть.")
        contractor = Contractor(
            name=name,
            inn=inn,
            kpp=cls._digits(payload.kpp, 9),
            kpp_largest=cls._digits(payload.kpp_largest, 9),
            address=cls._clean(payload.address, 1000),
            phone=cls._clean(payload.phone, 50),
            email=cls._clean(payload.email, 255),
            notes=cls._clean(payload.notes, 5000),
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(contractor)
        db.session.flush()
        AuditService.log(
            user_id=user_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.CONTRACTOR.value,
            entity_id=contractor.id,
            description=f"Создан подрядчик {contractor.name}",
            new_values={"name": contractor.name, "inn": contractor.inn},
        )
        db.session.commit()
        return contractor

    @classmethod
    def update(
        cls, contractor: Contractor, payload: ContractorPayload, user_id: uuid.UUID
    ) -> Contractor:
        name = cls._clean(payload.name, 500)
        if not name:
            raise ValidationError("Укажите наименование подрядчика.")
        inn = cls._digits(payload.inn, 12)
        if inn:
            other = ContractorRepository.get_by_inn(inn)
            if other is not None and other.id != contractor.id:
                raise ValidationError("Подрядчик с таким ИНН уже есть.")
        contractor.name = name
        contractor.inn = inn
        contractor.kpp = cls._digits(payload.kpp, 9)
        contractor.kpp_largest = cls._digits(payload.kpp_largest, 9)
        contractor.address = cls._clean(payload.address, 1000)
        contractor.phone = cls._clean(payload.phone, 50)
        contractor.email = cls._clean(payload.email, 255)
        contractor.notes = cls._clean(payload.notes, 5000)
        contractor.updated_by = user_id
        AuditService.log(
            user_id=user_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.CONTRACTOR.value,
            entity_id=contractor.id,
            description=f"Обновлён подрядчик {contractor.name}",
        )
        db.session.commit()
        return contractor

    @classmethod
    def soft_delete(cls, contractor: Contractor, user_id: uuid.UUID) -> None:
        contractor.soft_delete(user_id)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.SOFT_DELETE.value,
            entity_type=EntityType.CONTRACTOR.value,
            entity_id=contractor.id,
            description=f"Удалён подрядчик {contractor.name}",
        )
        db.session.commit()
