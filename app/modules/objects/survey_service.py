"""Обследование объекта: опоры на карте лота, без записи в мониторинг IRZ."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from app.core.audit_service import AuditService
from app.core.exceptions import NotFoundError, ValidationError
from app.extensions import db
from app.models.enums import AuditAction, EntityType, SurveyPoleKind, SurveyPoleType
from app.models.work_objects.object_survey_pole import ObjectSurveyPole
from app.models.work_objects.work_object import WorkObject

KIND_LABELS = {
    SurveyPoleKind.EXISTING.value: "Существующая",
    SurveyPoleKind.PLANNED.value: "Новая",
}
TYPE_LABELS = {
    SurveyPoleType.CONCRETE.value: "ЖБ",
    SurveyPoleType.METAL.value: "Металлическая",
    SurveyPoleType.OTHER.value: "Другое",
}
ALLOWED_KINDS = frozenset(KIND_LABELS)
ALLOWED_TYPES = frozenset(TYPE_LABELS)
ALLOWED_SOURCES = frozenset({"gps", "manual"})


def _as_decimal(value, *, field: str) -> Decimal:
    if value is None or value == "":
        raise ValidationError(f"Укажите {field}.")
    try:
        number = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"Некорректное значение: {field}.") from exc
    if not number.is_finite():
        raise ValidationError(f"Некорректное значение: {field}.")
    return number


class ObjectSurveyService:
    @staticmethod
    def count_for_object(object_id: uuid.UUID) -> int:
        return int(
            db.session.scalar(
                db.select(func.count(ObjectSurveyPole.id)).where(
                    ObjectSurveyPole.object_id == object_id,
                    ObjectSurveyPole.active_filter(),
                )
            )
            or 0
        )

    @staticmethod
    def summary(object_id: uuid.UUID) -> dict[str, int]:
        rows = db.session.execute(
            db.select(ObjectSurveyPole.kind, func.count(ObjectSurveyPole.id))
            .where(
                ObjectSurveyPole.object_id == object_id,
                ObjectSurveyPole.active_filter(),
            )
            .group_by(ObjectSurveyPole.kind)
        ).all()
        by_kind = {kind: int(count) for kind, count in rows}
        existing = by_kind.get(SurveyPoleKind.EXISTING.value, 0)
        planned = by_kind.get(SurveyPoleKind.PLANNED.value, 0)
        return {"existing": existing, "planned": planned, "total": existing + planned}

    @classmethod
    def list_poles(cls, obj: WorkObject) -> list[ObjectSurveyPole]:
        return list(
            db.session.scalars(
                db.select(ObjectSurveyPole)
                .where(
                    ObjectSurveyPole.object_id == obj.id,
                    ObjectSurveyPole.active_filter(),
                )
                .order_by(ObjectSurveyPole.sequence, ObjectSurveyPole.created_at)
            )
        )

    @classmethod
    def get_pole(cls, obj: WorkObject, pole_id: uuid.UUID) -> ObjectSurveyPole:
        pole = db.session.scalar(
            db.select(ObjectSurveyPole).where(
                ObjectSurveyPole.id == pole_id,
                ObjectSurveyPole.object_id == obj.id,
                ObjectSurveyPole.active_filter(),
            )
        )
        if pole is None:
            raise NotFoundError("Опора обследования не найдена.")
        return pole

    @classmethod
    def to_dict(cls, pole: ObjectSurveyPole) -> dict:
        return {
            "id": str(pole.id),
            "kind": pole.kind,
            "kind_label": KIND_LABELS.get(pole.kind, pole.kind),
            "pole_type": pole.pole_type,
            "type_label": TYPE_LABELS.get(pole.pole_type, pole.pole_type),
            "lat": float(pole.latitude),
            "lng": float(pole.longitude),
            "accuracy_m": float(pole.accuracy_m) if pole.accuracy_m is not None else None,
            "source": pole.source,
            "sequence": pole.sequence,
            "note": pole.note or "",
        }

    @classmethod
    def create_pole(cls, obj: WorkObject, payload: dict, user_id: uuid.UUID) -> ObjectSurveyPole:
        kind = cls._kind(payload.get("kind"))
        pole_type = cls._type(payload.get("pole_type"))
        lat, lng = cls._coordinates(payload.get("lat"), payload.get("lng"))
        source = cls._source(payload.get("source"))
        accuracy = cls._accuracy(payload.get("accuracy_m"))
        note = cls._note(payload.get("note"))
        next_seq = (
            db.session.scalar(
                db.select(func.coalesce(func.max(ObjectSurveyPole.sequence), 0)).where(
                    ObjectSurveyPole.object_id == obj.id,
                    ObjectSurveyPole.active_filter(),
                )
            )
            or 0
        ) + 1
        pole = ObjectSurveyPole(
            object_id=obj.id,
            kind=kind,
            pole_type=pole_type,
            latitude=lat,
            longitude=lng,
            accuracy_m=accuracy,
            source=source,
            sequence=next_seq,
            note=note,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(pole)
        db.session.flush()
        AuditService.log(
            user_id=user_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Обследование: добавлена опора {KIND_LABELS[kind]} / {TYPE_LABELS[pole_type]}",
            new_values=cls.to_dict(pole),
        )
        db.session.commit()
        return pole

    @classmethod
    def update_pole(
        cls,
        obj: WorkObject,
        pole: ObjectSurveyPole,
        payload: dict,
        user_id: uuid.UUID,
    ) -> ObjectSurveyPole:
        old = cls.to_dict(pole)
        if "kind" in payload:
            pole.kind = cls._kind(payload.get("kind"))
        if "pole_type" in payload:
            pole.pole_type = cls._type(payload.get("pole_type"))
        if "lat" in payload or "lng" in payload:
            lat, lng = cls._coordinates(
                payload.get("lat", pole.latitude),
                payload.get("lng", pole.longitude),
            )
            pole.latitude = lat
            pole.longitude = lng
        if "accuracy_m" in payload:
            pole.accuracy_m = cls._accuracy(payload.get("accuracy_m"))
        if "source" in payload:
            pole.source = cls._source(payload.get("source"))
        if "note" in payload:
            pole.note = cls._note(payload.get("note"))
        pole.updated_by = user_id
        db.session.flush()
        AuditService.log(
            user_id=user_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Обследование: изменена опора №{pole.sequence}",
            old_values=old,
            new_values=cls.to_dict(pole),
        )
        db.session.commit()
        return pole

    @classmethod
    def delete_pole(cls, obj: WorkObject, pole: ObjectSurveyPole, user_id: uuid.UUID) -> None:
        snapshot = cls.to_dict(pole)
        pole.soft_delete(user_id)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.SOFT_DELETE.value,
            entity_type=EntityType.WORK_OBJECT.value,
            entity_id=obj.id,
            description=f"Обследование: удалена опора №{pole.sequence}",
            old_values=snapshot,
        )
        db.session.commit()

    @staticmethod
    def _kind(value) -> str:
        kind = str(value or "").strip()
        if kind not in ALLOWED_KINDS:
            raise ValidationError("Укажите вид опоры: существующая или новая.")
        return kind

    @staticmethod
    def _type(value) -> str:
        pole_type = str(value or "").strip()
        if pole_type not in ALLOWED_TYPES:
            raise ValidationError("Укажите тип опоры: ЖБ, металлическая или другое.")
        return pole_type

    @staticmethod
    def _source(value) -> str:
        source = str(value or "manual").strip() or "manual"
        if source not in ALLOWED_SOURCES:
            raise ValidationError("Источник координат: gps или manual.")
        return source

    @staticmethod
    def _note(value) -> str | None:
        text = str(value or "").strip()
        return text[:500] or None

    @staticmethod
    def _accuracy(value) -> Decimal | None:
        if value is None or value == "":
            return None
        number = _as_decimal(value, field="точность GPS")
        if number < 0 or number > 10000:
            raise ValidationError("Точность GPS вне допустимого диапазона.")
        return number.quantize(Decimal("0.01"))

    @staticmethod
    def _coordinates(lat_raw, lng_raw) -> tuple[Decimal, Decimal]:
        lat = _as_decimal(lat_raw, field="широту")
        lng = _as_decimal(lng_raw, field="долготу")
        if not Decimal("-90") <= lat <= Decimal("90"):
            raise ValidationError("Широта вне диапазона −90…90.")
        if not Decimal("-180") <= lng <= Decimal("180"):
            raise ValidationError("Долгота вне диапазона −180…180.")
        if lat == 0 and lng == 0:
            raise ValidationError("Координаты 0,0 не принимаются.")
        return lat.quantize(Decimal("0.0000001")), lng.quantize(Decimal("0.0000001"))
