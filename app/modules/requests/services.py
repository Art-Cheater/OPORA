"""Сервисы модуля заявок."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from flask import current_app, request, url_for
from werkzeug.datastructures import FileStorage

from app.core.audit_service import AuditService
from app.core.exceptions import NotFoundError, ValidationError
from app.extensions import db
from app.models.auth.position import Position
from app.models.auth.user import User
from app.models.communication.comment import Comment
from app.models.communication.notification import Notification
from app.models.enums import AuditAction, EntityType, NotificationType
from app.models.files.attachment import Attachment
from app.models.requests.request import Request
from app.models.requests.request_history import RequestHistory
from app.models.requests.request_material import RequestMaterial
from app.models.requests.request_status import RequestStatus
from app.modules.requests.districts import normalize_request_district
from app.modules.requests.repositories import RequestRepository
from app.modules.requests.workflow import (
    HISTORY_ACCEPT_MASTER,
    HISTORY_ASSIGN_MASTER,
    HISTORY_CANCEL,
    HISTORY_COMPLETE,
    HISTORY_EMERGENCY_DEPARTED,
    HISTORY_START_WORK,
    HISTORY_STATUS_CHANGE,
    STATUS_ACCEPTED_BY_MASTER,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_EMERGENCY_DISPATCHED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    OPEN_STATUS_CODES,
    can_transition,
)


@dataclass
class RequestPayload:
    number: str
    title: str
    description: str | None
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
    pp: str | None
    received_at: Any
    dispatcher_name: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    applicant_name: str
    priority: str
    status_id: uuid.UUID
    responsible_id: uuid.UUID | None
    executor_id: uuid.UUID | None
    journal_id: uuid.UUID | None = None
    has_barrier: bool = False
    barrier_phone: str | None = None
    for_beresnev: bool = False


class RequestService:
    """CRUD + workflow + аудит + история изменений заявок."""

    TRACKED_FIELDS = [
        "number",
        "journal_id",
        "title",
        "description",
        "address",
        "original_address",
        "normalized_address",
        "region",
        "district",
        "settlement",
        "street",
        "house",
        "address_source",
        "address_external_id",
        "pp",
        "received_at",
        "dispatcher_name",
        "latitude",
        "longitude",
        "phone",
        "applicant_name",
        "priority",
        "status_id",
        "responsible_id",
        "executor_id",
        "has_barrier",
        "barrier_phone",
        "for_beresnev",
        "repeat_count",
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

    @staticmethod
    def normalize_address(address: str | None) -> str:
        from app.modules.requests.address_format import normalize_address as _norm

        return _norm(address)

    @staticmethod
    def format_address(address: str | None) -> str:
        from app.modules.requests.address_format import format_address as _fmt

        return _fmt(address)

    @classmethod
    def get_status_by_code(cls, code: str) -> RequestStatus:
        status = db.session.scalar(
            db.select(RequestStatus).where(
                RequestStatus.code == code,
                RequestStatus.active_filter(),
                RequestStatus.is_active.is_(True),
            )
        )
        if status is None:
            raise ValidationError(f"Статус «{code}» не найден в справочнике.")
        return status

    @classmethod
    def validate_payload(cls, payload: RequestPayload) -> None:
        if not payload.number.strip():
            raise ValidationError("Номер заявки обязателен.")
        if not (payload.address or "").strip():
            raise ValidationError("Адрес обязателен.")
        if payload.received_at is None:
            raise ValidationError("Укажите дату и время получения заявки.")
        cls._prepare_address(payload)
        if not payload.address:
            raise ValidationError("Адрес обязателен.")
        journal = RequestRepository.get_journal(payload.journal_id)
        if journal is None:
            journal = RequestRepository.get_default_journal()
        payload.journal_id = journal.id
        if payload.latitude is not None and not Decimal("-90") <= payload.latitude <= Decimal("90"):
            raise ValidationError("Широта должна быть в диапазоне от -90 до 90.")
        if payload.longitude is not None and not Decimal("-180") <= payload.longitude <= Decimal("180"):
            raise ValidationError("Долгота должна быть в диапазоне от -180 до 180.")
        # title заполняется из адреса автоматически
        if not (payload.title or "").strip():
            payload.title = payload.address[:500]
        if not (payload.applicant_name or "").strip():
            payload.applicant_name = "—"
        if payload.has_barrier:
            if not cls._normalize_text(payload.barrier_phone):
                raise ValidationError("Укажите телефон для шлагбаума.")
        else:
            payload.barrier_phone = None

        status = db.session.get(RequestStatus, payload.status_id)
        if status is None or status.deleted_at is not None:
            raise ValidationError("Выбранный статус не найден.")

    @classmethod
    def _prepare_address(cls, payload: RequestPayload) -> None:
        """Применяет выбранную подсказку или быстрый локальный fallback без сети."""

        from app.core.address import HeuristicGeocodingProvider

        current_address = (payload.address or "").strip()
        selected = (payload.normalized_address or "").strip()
        original = (payload.original_address or "").strip()
        selection_is_current = bool(selected) and current_address in {
            selected,
            selected[:500],
            original,
        }
        submitted = (
            (original or current_address).strip()
            if selection_is_current
            else current_address
        )
        if selection_is_current:
            payload.original_address = submitted
            payload.normalized_address = selected
            payload.address = selected[:500]
            payload.region = cls._normalize_text(payload.region)
            payload.district = normalize_request_district(payload.district)
            payload.settlement = cls._normalize_text(payload.settlement)
            payload.street = cls._normalize_text(payload.street)
            payload.house = cls._normalize_text(payload.house)
            payload.address_source = cls._normalize_text(payload.address_source) or "selected"
            payload.address_external_id = cls._normalize_text(payload.address_external_id)
            if payload.latitude is None or payload.longitude is None:
                latlng = cls._geocode_latlng(selected or submitted)
                if latlng:
                    payload.latitude, payload.longitude = latlng
            return

        payload.latitude = None
        payload.longitude = None
        from app.core.address import get_address_suggestion_service
        from app.modules.requests.address_format import split_address_query

        try:
            fallback = get_address_suggestion_service().suggest(submitted, limit=8)
        except Exception:
            fallback = HeuristicGeocodingProvider().search(submitted, limit=8)
        if not fallback:
            payload.original_address = submitted
            payload.normalized_address = submitted
            payload.address = submitted[:500]
            payload.region = None
            payload.district = normalize_request_district(payload.district)
            payload.settlement = None
            payload.street = None
            payload.house = None
            payload.address_source = "manual"
            payload.address_external_id = None
            return
        suggestion = fallback[0]
        from app.core.address.catalog import resolve_catalog_district

        _kind, street_name, house = split_address_query(submitted)
        street_kind = suggestion.street.split(" ", 1)[0] if suggestion.street else (_kind or "улица")
        street_only = (
            suggestion.street.split(" ", 1)[1]
            if suggestion.street and " " in suggestion.street
            else street_name
        )
        form_district = normalize_request_district(payload.district)
        # При наличии дома район из подсказки (OSM) важнее «главной» улицы справочника
        if house and suggestion.district:
            resolved = suggestion.district
        else:
            resolved = resolve_catalog_district(
                street_only or street_name or "",
                street_kind,
                preferred=form_district or suggestion.district,
            )
        payload.original_address = submitted
        payload.normalized_address = suggestion.normalized_address
        payload.address = suggestion.normalized_address[:500]
        payload.region = suggestion.region
        payload.district = form_district or normalize_request_district(resolved)
        payload.settlement = suggestion.settlement
        payload.street = suggestion.street
        payload.house = suggestion.house or house or None
        payload.address_source = suggestion.address_source
        payload.address_external_id = suggestion.address_external_id
        payload.latitude = suggestion.latitude
        payload.longitude = suggestion.longitude
        if payload.latitude is None or payload.longitude is None:
            latlng = cls._geocode_latlng(payload.normalized_address or submitted)
            if latlng:
                payload.latitude, payload.longitude = latlng

    @staticmethod
    def _geocode_latlng(query: str) -> tuple[Decimal, Decimal] | None:
        """Короткий запрос к Nominatim. Без suggest() — он для домов ждёт до 2.5 с и блокирует воркер."""
        text = (query or "").strip()
        if len(text) < 3:
            return None
        try:
            from app.core.address import get_address_suggestion_service

            service = get_address_suggestion_service()
            if not hasattr(service, "_search_provider"):
                return None
            regional = text
            folded = text.casefold()
            if "киров" not in folded:
                regional = f"{text}, Киров, Кировская область"
            old_timeout = service.provider_timeout_seconds
            # Не держим HTTP-воркер: таймаут геокодера жёстко ограничен.
            service.provider_timeout_seconds = min(max(old_timeout, 0.3), 1.0)
            try:
                candidates = service._search_provider(regional, 3) or []
            finally:
                service.provider_timeout_seconds = old_timeout
        except Exception:
            return None
        for hit in candidates:
            if hit.latitude is None or hit.longitude is None:
                continue
            try:
                return Decimal(str(hit.latitude)), Decimal(str(hit.longitude))
            except Exception:
                continue
        return None

    @classmethod
    def fill_missing_coordinates(cls, req: Request, *, persist: bool = True) -> bool:
        """Дополнить lat/lng у заявки без координат (каталог улиц их не хранит)."""
        if req.latitude is not None and req.longitude is not None:
            return True
        query = (req.normalized_address or req.address or "").strip()
        latlng = cls._geocode_latlng(query)
        if not latlng:
            return False
        req.latitude, req.longitude = latlng
        if persist:
            db.session.commit()
        return True

    @staticmethod
    def _snapshot(req: Request) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field in RequestService.TRACKED_FIELDS:
            value = getattr(req, field)
            if isinstance(value, uuid.UUID):
                data[field] = str(value)
            elif isinstance(value, Decimal):
                data[field] = float(value)
            elif hasattr(value, "isoformat"):
                data[field] = value.isoformat()
            else:
                data[field] = value
        return data

    @staticmethod
    def _diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
        changes: dict[str, dict[str, Any]] = {}
        for key, old_val in old.items():
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
            entity_type=EntityType.REQUEST.value,
            entity_id=entity_id,
            description=description,
            old_values=old_values,
            new_values=new_values,
        )

    @staticmethod
    def _log_history(
        req: Request,
        user_id: uuid.UUID,
        action: str,
        comment: str | None,
        details: dict[str, Any] | None,
        previous_status_id: uuid.UUID | None = None,
    ) -> None:
        db.session.add(
            RequestHistory(
                request_id=req.id,
                status_id=req.status_id,
                previous_status_id=previous_status_id,
                action=action,
                comment=comment,
                details=details,
                changed_by=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    @classmethod
    def _notify(
        cls,
        *,
        user_id: uuid.UUID,
        title: str,
        message: str,
        request_id: uuid.UUID,
        actor_id: uuid.UUID,
        ntype: str = NotificationType.INFO.value,
    ) -> None:
        db.session.add(
            Notification(
                user_id=user_id,
                title=title,
                message=message,
                type=ntype,
                entity_type=EntityType.REQUEST.value,
                entity_id=request_id,
                link=url_for("requests.detail", request_id=request_id),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

    @classmethod
    def _lock_request(cls, request_id: uuid.UUID) -> Request:
        req = db.session.scalar(
            db.select(Request)
            .where(Request.id == request_id, Request.active_filter())
            .with_for_update()
        )
        if req is None:
            raise NotFoundError("Заявка не найдена.")
        # Подтянуть статус в той же транзакции
        _ = req.status
        return req

    @classmethod
    def _apply_status(
        cls,
        req: Request,
        new_status: RequestStatus,
        user_id: uuid.UUID,
        *,
        history_action: str,
        history_comment: str,
        details: dict[str, Any] | None = None,
        audit_description: str | None = None,
        enforce_transition: bool = True,
    ) -> uuid.UUID:
        old_status = req.status
        old_code = old_status.code if old_status else None
        if enforce_transition and old_code and not can_transition(old_code, new_status.code):
            raise ValidationError(
                f"Переход статуса «{old_status.name if old_status else old_code}» "
                f"→ «{new_status.name}» недопустим."
            )

        previous_status_id = req.status_id
        old_snapshot = cls._snapshot(req)
        req.status_id = new_status.id
        req.updated_by = user_id
        new_snapshot = cls._snapshot(req)

        cls._log_audit(
            user_id,
            AuditAction.STATUS_CHANGE.value,
            req.id,
            audit_description or history_comment,
            old_snapshot,
            new_snapshot,
        )
        cls._log_history(
            req,
            user_id,
            history_action,
            history_comment,
            {
                **(details or {}),
                "from_status": old_code,
                "to_status": new_status.code,
                "from_status_name": old_status.name if old_status else None,
                "to_status_name": new_status.name,
            },
            previous_status_id=previous_status_id,
        )
        return previous_status_id

    @classmethod
    def create_request(cls, payload: RequestPayload, user_id: uuid.UUID) -> Request:
        cls.validate_payload(payload)
        exists = db.session.scalar(
            db.select(Request.id).where(
                Request.number == payload.number.strip(),
                Request.journal_id == payload.journal_id,
            ).limit(1)
        )
        if exists is not None:
            raise ValidationError("Заявка с таким номером уже есть в этом журнале.")

        new_status = cls.get_status_by_code(STATUS_NEW)

        req = Request(
            number=payload.number.strip(),
            title=payload.title.strip() or payload.address[:500],
            description=cls._normalize_text(payload.description),
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
            pp=cls._normalize_text(payload.pp),
            received_at=payload.received_at,
            dispatcher_name=cls._normalize_text(payload.dispatcher_name),
            latitude=payload.latitude,
            longitude=payload.longitude,
            phone=cls._normalize_text(payload.phone),
            applicant_name=(payload.applicant_name or "—").strip(),
            has_barrier=bool(payload.has_barrier),
            barrier_phone=cls._normalize_text(payload.barrier_phone),
            for_beresnev=bool(payload.for_beresnev),
            repeat_count=0,
            repeat_dates=[],
            priority=payload.priority,
            journal_id=payload.journal_id,
            status_id=new_status.id,
            responsible_id=payload.responsible_id,
            executor_id=payload.executor_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(req)
        try:
            db.session.flush()
        except IntegrityError as exc:
            db.session.rollback()
            raise ValidationError("Заявка с таким номером уже есть в этом журнале.") from exc
        RequestRepository.note_used_number(req.journal_id, req.number)

        snapshot = cls._snapshot(req)
        cls._log_audit(
            user_id,
            AuditAction.CREATE.value,
            req.id,
            f"Создана заявка {req.number}",
            None,
            snapshot,
        )
        cls._log_history(
            req,
            user_id,
            "create",
            "Диспетчер создал заявку",
            {"created": snapshot, "status": STATUS_NEW},
        )
        db.session.commit()
        return req

    @classmethod
    def update_request(
        cls,
        req: Request,
        payload: RequestPayload,
        user_id: uuid.UUID,
    ) -> Request:
        cls.validate_payload(payload)
        old_snapshot = cls._snapshot(req)
        previous_status_id = req.status_id
        old_description = req.description
        status_changed = payload.status_id != req.status_id
        if status_changed:
            new_status = db.session.get(RequestStatus, payload.status_id)
            if new_status is None or new_status.deleted_at is not None:
                raise ValidationError("Выбранный статус не найден.")
            req.status_id = new_status.id
            db.session.expire(req, ["status"])

        req.number = payload.number.strip()
        req.journal_id = payload.journal_id
        req.title = (payload.title.strip() or payload.address)[:500]
        req.description = cls._normalize_text(payload.description)
        req.address = payload.address
        req.original_address = payload.original_address
        req.normalized_address = payload.normalized_address
        req.region = payload.region
        req.district = payload.district
        req.settlement = payload.settlement
        req.street = payload.street
        req.house = payload.house
        req.address_source = payload.address_source
        req.address_external_id = payload.address_external_id
        req.pp = cls._normalize_text(payload.pp)
        req.received_at = payload.received_at
        req.dispatcher_name = cls._normalize_text(payload.dispatcher_name)
        req.latitude = payload.latitude
        req.longitude = payload.longitude
        req.phone = cls._normalize_text(payload.phone)
        req.applicant_name = (payload.applicant_name or "—").strip()
        req.has_barrier = bool(payload.has_barrier)
        req.barrier_phone = cls._normalize_text(payload.barrier_phone)
        req.for_beresnev = bool(payload.for_beresnev)
        req.priority = payload.priority
        req.executor_id = payload.executor_id
        req.responsible_id = payload.responsible_id
        req.updated_by = user_id

        new_snapshot = cls._snapshot(req)
        changes = cls._diff(old_snapshot, new_snapshot)
        if not changes:
            return req

        description_changed = "description" in changes
        audit_action = AuditAction.STATUS_CHANGE.value if status_changed else AuditAction.UPDATE.value
        history_action = HISTORY_STATUS_CHANGE if status_changed else "update"
        history_comment = "Обновление заявки"
        history_details: dict[str, Any] = {"changes": changes}
        if status_changed:
            old_status = db.session.get(RequestStatus, previous_status_id)
            history_comment = (
                f"Статус изменён при редактировании: "
                f"{old_status.name if old_status else '—'} → {req.status.name if req.status else '—'}"
            )
            history_details["from_status"] = old_status.code if old_status else None
            history_details["to_status"] = req.status.code if req.status else None
        if description_changed:
            history_comment = "Диспетчер дополнил описание заявки"
            history_details["description"] = {
                "old": old_description,
                "new": req.description,
            }

        cls._log_audit(
            user_id,
            audit_action,
            req.id,
            f"Обновлена заявка {req.number}",
            old_snapshot,
            new_snapshot,
        )
        cls._log_history(
            req,
            user_id,
            history_action,
            history_comment,
            history_details,
            previous_status_id=previous_status_id,
        )
        db.session.commit()
        return req

    @classmethod
    def mark_repeat_call(
        cls,
        req: Request,
        user_id: uuid.UUID,
        *,
        call_at: Any = None,
        phone: str | None = None,
        applicant_name: str | None = None,
        description: str | None = None,
        has_barrier: bool | None = None,
        barrier_phone: str | None = None,
    ) -> Request:
        """Зафиксировать повторное обращение на существующей открытой заявке."""
        from datetime import datetime, timezone

        if req.status is None or req.status.is_final:
            raise ValidationError("Повтор можно отметить только для открытой заявки.")

        when = call_at or datetime.now(timezone.utc)
        if isinstance(when, datetime) and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)

        old_snapshot = cls._snapshot(req)
        dates = list(req.repeat_dates or [])
        dates.append(when.isoformat())
        req.repeat_dates = dates
        req.repeat_count = int(req.repeat_count or 0) + 1

        if cls._normalize_text(phone):
            req.phone = cls._normalize_text(phone)
        if cls._normalize_text(applicant_name):
            req.applicant_name = applicant_name.strip()
        if cls._normalize_text(description):
            # Дописываем к описанию, не затираем
            note = description.strip()
            if req.description:
                req.description = f"{req.description}\n\n[Повтор {when.strftime('%d.%m.%Y %H:%M')}]\n{note}"
            else:
                req.description = f"[Повтор {when.strftime('%d.%m.%Y %H:%M')}]\n{note}"
        if has_barrier is not None:
            req.has_barrier = bool(has_barrier)
            if req.has_barrier:
                if cls._normalize_text(barrier_phone):
                    req.barrier_phone = cls._normalize_text(barrier_phone)
            else:
                req.barrier_phone = None

        req.updated_by = user_id
        new_snapshot = cls._snapshot(req)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            req.id,
            f"Повторное обращение по заявке {req.number} (×{req.repeat_count})",
            old_snapshot,
            new_snapshot,
        )
        cls._log_history(
            req,
            user_id,
            "repeat_call",
            f"Повторное обращение зафиксировано ({when.strftime('%d.%m.%Y %H:%M')})",
            {
                "repeat_count": req.repeat_count,
                "call_at": when.isoformat(),
            },
        )
        db.session.commit()
        return req

    @classmethod
    def mark_emergency_departed(cls, request_id: uuid.UUID, user_id: uuid.UUID) -> Request:
        """Диспетчер отмечает: выехала аварийная бригада (строка становится жёлтой)."""
        req = cls._lock_request(request_id)
        if req.status.code != STATUS_NEW:
            raise ValidationError(
                "Отметить выезд можно только для заявки в статусе «Новая»."
            )

        new_status = cls.get_status_by_code(STATUS_EMERGENCY_DISPATCHED)
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_EMERGENCY_DEPARTED,
            history_comment="Диспетчер отметил: выехала аварийная бригада",
            audit_description=f"Аварийная бригада выехала по заявке {req.number}",
        )
        db.session.commit()
        return req

    @classmethod
    def assign_master(
        cls,
        request_id: uuid.UUID,
        master_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Request:
        req = cls._lock_request(request_id)
        if req.status.code not in (STATUS_EMERGENCY_DISPATCHED, STATUS_NEW):
            raise ValidationError(
                "Назначить мастера можно из статуса «Новая» или «Выехала аварийная бригада»."
            )

        master = cls._ensure_master_user(master_id)
        new_status = cls.get_status_by_code(STATUS_ACCEPTED_BY_MASTER)
        req.responsible_id = master.id
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_ASSIGN_MASTER,
            history_comment=f"Диспетчер передал заявку мастеру {master.full_name}",
            details={"master_id": str(master.id), "master_name": master.full_name},
            audit_description=(
                f"Диспетчер передал заявку {req.number} мастеру {master.full_name}"
            ),
        )
        cls._notify(
            user_id=master.id,
            title="Назначена заявка",
            message=f"Вам назначена заявка №{req.number}",
            request_id=req.id,
            actor_id=user_id,
        )
        db.session.commit()
        return req

    @classmethod
    def accept_by_master(cls, request_id: uuid.UUID, user_id: uuid.UUID) -> Request:
        req = cls._lock_request(request_id)
        if req.responsible_id is not None or req.status.code == STATUS_ACCEPTED_BY_MASTER:
            raise ValidationError("Заявка уже принята другим мастером.")
        if req.status.code != STATUS_EMERGENCY_DISPATCHED:
            raise ValidationError(
                "Принять можно только заявку со статусом «Выехала аварийная бригада»."
            )

        master = db.session.get(User, user_id)
        if master is None or master.deleted_at is not None:
            raise ValidationError("Пользователь не найден.")

        new_status = cls.get_status_by_code(STATUS_ACCEPTED_BY_MASTER)
        req.responsible_id = master.id
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_ACCEPT_MASTER,
            history_comment=f"Мастер {master.full_name} самостоятельно принял заявку",
            details={"master_id": str(master.id), "master_name": master.full_name},
            audit_description=(
                f"Мастер {master.full_name} принял заявку {req.number}"
            ),
        )

        if req.created_by and req.created_by != user_id:
            cls._notify(
                user_id=req.created_by,
                title="Заявка принята мастером",
                message=f"Заявка №{req.number} принята мастером {master.full_name}",
                request_id=req.id,
                actor_id=user_id,
                ntype=NotificationType.SUCCESS.value,
            )
        db.session.commit()
        return req

    @classmethod
    def start_work(cls, request_id: uuid.UUID, user_id: uuid.UUID) -> Request:
        req = cls._lock_request(request_id)
        if req.status.code != STATUS_ACCEPTED_BY_MASTER:
            raise ValidationError("Начать работу можно после принятия заявки мастером.")
        new_status = cls.get_status_by_code(STATUS_IN_PROGRESS)
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_START_WORK,
            history_comment="Заявка переведена в работу",
            audit_description=f"Заявка {req.number} переведена в работу",
        )
        db.session.commit()
        return req

    @classmethod
    def mark_in_progress_in_session(cls, request_id: uuid.UUID, user_id: uuid.UUID) -> Request:
        """Перевести заявку «В работе» без commit. Для сохранения плана работ."""
        req = cls._lock_request(request_id)
        if req.status.code == STATUS_IN_PROGRESS:
            return req
        if req.status.code not in OPEN_STATUS_CODES:
            raise ValidationError("Заявку в этом статусе нельзя взять в работу.")
        new_status = cls.get_status_by_code(STATUS_IN_PROGRESS)
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_START_WORK,
            history_comment="Заявка включена в план работ",
            audit_description=f"Заявка {req.number} включена в план работ",
        )
        return req

    @classmethod
    def restore_from_plan_in_session(cls, request_id: uuid.UUID, user_id: uuid.UUID, previous_code: str | None) -> Request:
        """Вернуть статус, если система перевела заявку в работу из-за плана."""
        req = cls._lock_request(request_id)
        previous = (previous_code or "").strip()
        current = req.status.code if req.status else ""
        if not previous or current != STATUS_IN_PROGRESS or previous == STATUS_IN_PROGRESS:
            return req
        new_status = cls.get_status_by_code(previous)
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_STATUS_CHANGE,
            history_comment="Заявка возвращена из плана работ",
            audit_description=f"Заявка {req.number} возвращена из плана работ",
            enforce_transition=False,
        )
        return req

    @classmethod
    def complete_request(
        cls,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        comment: str | None = None,
        commit: bool = True,
    ) -> Request:
        """Отметить заявку выполненной: текущий открытый статус → completed."""
        req = cls._lock_request(request_id)
        if req.status.code not in OPEN_STATUS_CODES:
            raise ValidationError("Заявку в этом статусе нельзя отметить выполненной.")
        new_status = cls.get_status_by_code(STATUS_COMPLETED)
        history_comment = (comment or "").strip() or "Заявка отмечена выполненной"
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_COMPLETE,
            history_comment=history_comment,
            audit_description=f"Заявка {req.number} выполнена",
        )
        if commit:
            db.session.commit()
        return req

    @classmethod
    def cancel_request(cls, request_id: uuid.UUID, user_id: uuid.UUID) -> Request:
        req = cls._lock_request(request_id)
        if req.status.code in (STATUS_COMPLETED, STATUS_CANCELLED):
            raise ValidationError("Эту заявку нельзя отменить.")
        new_status = cls.get_status_by_code(STATUS_CANCELLED)
        # can_transition already allows cancel from intermediate states
        cls._apply_status(
            req,
            new_status,
            user_id,
            history_action=HISTORY_CANCEL,
            history_comment="Заявка отменена",
            audit_description=f"Заявка {req.number} отменена",
        )
        db.session.commit()
        return req

    @staticmethod
    def _ensure_master_user(master_id: uuid.UUID) -> User:
        master = db.session.scalar(
            db.select(User)
            .outerjoin(Position, User.position_id == Position.id)
            .where(
                User.id == master_id,
                User.active_filter(),
                User.is_active.is_(True),
                User.is_blocked.is_(False),
            )
        )
        if master is None:
            raise ValidationError("Выбранный мастер не найден или неактивен.")

        is_master_position = (
            master.position_ref is not None
            and master.position_ref.deleted_at is None
            and master.position_ref.code == "master"
        )
        is_master_role = master.has_role("master")
        if not (is_master_position or is_master_role):
            raise ValidationError("В списке мастеров можно выбрать только сотрудника с должностью «Мастер».")
        return master

    @classmethod
    def add_comment(cls, req: Request, body: str, user_id: uuid.UUID) -> Comment:
        body = body.strip()
        if not body:
            raise ValidationError("Комментарий не может быть пустым.")
        comment = Comment(
            author_id=user_id,
            entity_type=EntityType.REQUEST.value,
            entity_id=req.id,
            body=body,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(comment)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            req.id,
            "Добавлен комментарий к заявке",
            None,
            {"comment": body},
        )
        cls._log_history(req, user_id, "comment", "Добавлен комментарий", {"comment": body})
        db.session.commit()
        return comment

    @classmethod
    def add_attachment(
        cls,
        req: Request,
        *,
        file_storage: FileStorage,
        user_id: uuid.UUID,
    ) -> Attachment:
        from app.core.upload_utils import UploadValidationError, save_upload

        try:
            saved = save_upload(file_storage, relative_dir=f"requests/{req.id}")
        except UploadValidationError as exc:
            raise ValidationError(str(exc)) from exc
        attachment = Attachment(
            uploaded_by=user_id,
            entity_type=EntityType.REQUEST.value,
            entity_id=req.id,
            file_name=saved.file_name,
            mime_type=saved.mime_type,
            file_size=saved.file_size,
            storage_key=saved.storage_key,
            checksum=None,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(attachment)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            req.id,
            f"Добавлен файл к заявке: {saved.file_name}",
            None,
            {"attachment": saved.file_name, "mime_type": saved.mime_type},
        )
        cls._log_history(
            req,
            user_id,
            "attachment",
            "Добавлен файл",
            {"file_name": saved.file_name, "mime_type": saved.mime_type},
        )
        db.session.commit()
        return attachment

    @classmethod
    def add_attachments(
        cls,
        req: Request,
        *,
        file_storages: list,
        user_id: uuid.UUID,
    ) -> list[Attachment]:
        from app.core.upload_utils import UploadValidationError, save_upload

        if not file_storages:
            raise ValidationError("Выберите хотя бы один файл.")

        max_files = int(current_app.config.get("MAX_UPLOAD_FILES", 20))
        if len(file_storages) > max_files:
            raise ValidationError(f"За один раз можно загрузить не более {max_files} файлов.")

        created: list[Attachment] = []
        names: list[str] = []
        for file_storage in file_storages:
            try:
                saved = save_upload(file_storage, relative_dir=f"requests/{req.id}")
            except UploadValidationError as exc:
                raise ValidationError(str(exc)) from exc
            attachment = Attachment(
                uploaded_by=user_id,
                entity_type=EntityType.REQUEST.value,
                entity_id=req.id,
                file_name=saved.file_name,
                mime_type=saved.mime_type,
                file_size=saved.file_size,
                storage_key=saved.storage_key,
                checksum=None,
                created_by=user_id,
                updated_by=user_id,
            )
            db.session.add(attachment)
            created.append(attachment)
            names.append(saved.file_name)

        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            req.id,
            f"Добавлены файлы к заявке: {', '.join(names)}",
            None,
            {"attachments": names},
        )
        cls._log_history(
            req,
            user_id,
            "attachment",
            f"Добавлено файлов: {len(names)}",
            {"file_names": names},
        )
        db.session.commit()
        return created

    @classmethod
    def delete_attachment(
        cls,
        req: Request,
        attachment_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        attachment = db.session.scalar(
            db.select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.entity_type == EntityType.REQUEST.value,
                Attachment.entity_id == req.id,
                Attachment.active_filter(),
            )
        )
        if attachment is None:
            raise NotFoundError("Файл не найден.")

        file_name = attachment.file_name
        attachment.soft_delete(deleted_by=user_id)
        cls._log_audit(
            user_id,
            AuditAction.SOFT_DELETE.value,
            req.id,
            f"Удалён файл заявки: {file_name}",
            {"attachment": file_name},
            None,
        )
        cls._log_history(
            req,
            user_id,
            "attachment_delete",
            "Удалён файл",
            {"file_name": file_name},
        )
        db.session.commit()

    @classmethod
    def add_material(
        cls,
        req: Request,
        *,
        name: str,
        unit: str,
        quantity: Decimal,
        price: Decimal,
        notes: str | None,
        user_id: uuid.UUID,
    ) -> RequestMaterial:
        material = RequestMaterial(
            request_id=req.id,
            name=name.strip(),
            unit=unit.strip() or "шт",
            quantity=quantity,
            price=price,
            notes=cls._normalize_text(notes),
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(material)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            req.id,
            f"Добавлен материал: {material.name}",
            None,
            {"material": {"name": material.name, "quantity": float(material.quantity)}},
        )
        cls._log_history(
            req,
            user_id,
            "material",
            "Добавлен материал",
            {"name": material.name, "quantity": float(material.quantity), "unit": material.unit},
        )
        db.session.commit()
        return material

    @classmethod
    def delete_request(cls, req: Request, user_id: uuid.UUID) -> None:
        """Мягкое удаление заявки."""
        number = req.number
        req.soft_delete(deleted_by=user_id)
        cls._log_audit(
            user_id,
            AuditAction.SOFT_DELETE.value,
            req.id,
            f"Удалена заявка {number}",
        )
        db.session.commit()

    @classmethod
    def wipe_all(cls, user_id: uuid.UUID) -> int:
        """Полностью удалить все заявки и связанные строки (история, файлы, комментарии)."""
        from sqlalchemy import delete

        from app.models.custom_fields.custom_field_value import CustomFieldValue
        from app.models.waybills.waybill_stop import WaybillStop

        ids = list(db.session.scalars(db.select(Request.id)))
        if not ids:
            return 0
        kind = EntityType.REQUEST.value
        db.session.execute(delete(WaybillStop).where(WaybillStop.request_id.in_(ids)))
        db.session.execute(delete(RequestMaterial).where(RequestMaterial.request_id.in_(ids)))
        db.session.execute(delete(RequestHistory).where(RequestHistory.request_id.in_(ids)))
        db.session.execute(
            delete(Comment).where(Comment.entity_type == kind, Comment.entity_id.in_(ids))
        )
        db.session.execute(
            delete(Attachment).where(Attachment.entity_type == kind, Attachment.entity_id.in_(ids))
        )
        db.session.execute(
            delete(Notification).where(
                Notification.entity_type == kind, Notification.entity_id.in_(ids)
            )
        )
        db.session.execute(
            delete(CustomFieldValue).where(
                CustomFieldValue.entity_type == kind, CustomFieldValue.entity_id.in_(ids)
            )
        )
        db.session.execute(delete(Request).where(Request.id.in_(ids)))
        AuditService.log(
            user_id=user_id,
            action=AuditAction.DELETE.value,
            entity_type=kind,
            description=f"Полная очистка заявок: {len(ids)}",
            new_values={"count": len(ids)},
        )
        db.session.commit()
        return len(ids)

    @staticmethod
    def ensure_request(request_id: str) -> Request:
        req = db.session.get(Request, uuid.UUID(request_id))
        if req is None or req.deleted_at is not None:
            raise NotFoundError("Заявка не найдена.")
        return req
