"""Сервис пользовательских полей (EAV)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from flask import Request as FlaskRequest
from werkzeug.datastructures import ImmutableMultiDict

from app.core.exceptions import ValidationError
from app.core.permission_service import PermissionService
from app.extensions import db
from app.models.auth.field_definition import FieldDefinition
from app.models.auth.system_module import SystemModule
from app.models.auth.user import User
from app.models.custom_fields.constants import (
    CUSTOM_FIELD_MODULES,
    FIELD_TYPE_BOOLEAN,
    FIELD_TYPE_DATE,
    FIELD_TYPE_DATETIME,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_SELECT,
    FIELD_TYPE_TEXT,
    FIELD_TYPE_TEXTAREA,
)
from app.models.custom_fields.custom_field import CustomField
from app.models.custom_fields.custom_field_value import CustomFieldValue
from app.models.custom_fields.field_option import FieldOption

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,98}$")

ENTITY_URLS = {
    "requests": "/requests/{id}",
    "projects": "/projects/{id}",
    "contracts": "/contracts/{id}",
    "users": "/employees/{id}",
}


@dataclass
class OptionPayload:
    value: str
    label: str
    sort_order: int = 0


@dataclass
class CustomFieldPayload:
    module_code: str
    code: str
    name: str
    field_type: str
    description: str | None
    is_required: bool
    is_visible: bool
    sort_order: int
    options: list[OptionPayload]


class CustomFieldService:
    """CRUD метаданных и значений динамических полей."""

    @staticmethod
    def _normalize_code(code: str) -> str:
        return code.strip().lower().replace("-", "_").replace(" ", "_")

    @classmethod
    def _get_module(cls, module_code: str) -> SystemModule:
        mod = db.session.scalar(
            db.select(SystemModule).where(
                SystemModule.code == module_code,
                SystemModule.active_filter(),
            )
        )
        if mod is None:
            raise ValidationError(f"Модуль «{module_code}» не найден.")
        return mod

    @classmethod
    def _validate_code_unique(cls, module_id: uuid.UUID, code: str, exclude_id: uuid.UUID | None = None) -> None:
        stmt = db.select(CustomField).where(
            CustomField.module_id == module_id,
            CustomField.code == code,
            CustomField.active_filter(),
        )
        if exclude_id:
            stmt = stmt.where(CustomField.id != exclude_id)
        if db.session.scalar(stmt) is not None:
            raise ValidationError("Поле с таким кодом уже существует в модуле.")
        builtin = db.session.scalar(
            db.select(FieldDefinition).where(
                FieldDefinition.module_id == module_id,
                FieldDefinition.code == code,
                FieldDefinition.active_filter(),
            )
        )
        if builtin is not None:
            raise ValidationError("Код совпадает со встроенным полем модуля.")

    @classmethod
    def _sync_options(cls, field: CustomField, options: list[OptionPayload]) -> None:
        for opt in list(field.options):
            if opt.deleted_at is None:
                opt.soft_delete()
        for idx, payload in enumerate(options):
            db.session.add(
                FieldOption(
                    custom_field_id=field.id,
                    value=payload.value.strip(),
                    label=payload.label.strip(),
                    sort_order=payload.sort_order if payload.sort_order else idx * 10,
                )
            )

    @classmethod
    def create_field(cls, payload: CustomFieldPayload, actor_id: uuid.UUID) -> CustomField:
        code = cls._normalize_code(payload.code)
        if not CODE_PATTERN.match(code):
            raise ValidationError("Код: латиница, цифры, _, начинается с буквы (2–100 символов).")
        mod = cls._get_module(payload.module_code)
        if payload.module_code not in CUSTOM_FIELD_MODULES:
            raise ValidationError("Конструктор полей недоступен для этого модуля.")
        cls._validate_code_unique(mod.id, code)
        if payload.field_type == FIELD_TYPE_SELECT and not payload.options:
            raise ValidationError("Для выпадающего списка добавьте хотя бы один вариант.")

        field = CustomField(
            module_id=mod.id,
            code=code,
            name=payload.name.strip(),
            field_type=payload.field_type,
            description=(payload.description or "").strip() or None,
            is_required=payload.is_required,
            is_visible=payload.is_visible,
            sort_order=payload.sort_order,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.session.add(field)
        db.session.flush()
        if payload.field_type == FIELD_TYPE_SELECT:
            cls._sync_options(field, payload.options)
        db.session.commit()
        cls.clear_cache()
        return field

    @classmethod
    def update_field(cls, field: CustomField, payload: CustomFieldPayload, actor_id: uuid.UUID) -> CustomField:
        if payload.code.strip().lower() != field.code:
            raise ValidationError("Системный код нельзя изменить после создания.")
        mod = cls._get_module(payload.module_code)
        if payload.field_type == FIELD_TYPE_SELECT and not payload.options:
            raise ValidationError("Для выпадающего списка добавьте хотя бы один вариант.")

        field.name = payload.name.strip()
        field.field_type = payload.field_type
        field.description = (payload.description or "").strip() or None
        field.is_required = payload.is_required
        field.is_visible = payload.is_visible
        field.sort_order = payload.sort_order
        field.updated_by = actor_id
        if payload.field_type == FIELD_TYPE_SELECT:
            cls._sync_options(field, payload.options)
        db.session.commit()
        cls.clear_cache()
        return field

    @classmethod
    def delete_field(cls, field: CustomField, actor_id: uuid.UUID) -> None:
        field.soft_delete(deleted_by=actor_id)
        for val in field.values:
            if val.deleted_at is None:
                val.soft_delete(deleted_by=actor_id)
        db.session.commit()
        cls.clear_cache()

    @staticmethod
    def clear_cache() -> None:
        PermissionService.clear_cache()

    @staticmethod
    def list_for_module(module_code: str, *, include_hidden: bool = False) -> list[CustomField]:
        mod = db.session.scalar(
            db.select(SystemModule).where(SystemModule.code == module_code, SystemModule.active_filter())
        )
        if mod is None:
            return []
        stmt = db.select(CustomField).where(
            CustomField.module_id == mod.id,
            CustomField.active_filter(),
            CustomField.is_active.is_(True),
        )
        if not include_hidden:
            stmt = stmt.where(CustomField.is_visible.is_(True))
        stmt = stmt.order_by(CustomField.sort_order.asc(), CustomField.name.asc())
        return list(db.session.scalars(stmt))

    @staticmethod
    def get_by_id(field_id: uuid.UUID | str) -> CustomField | None:
        if isinstance(field_id, str):
            try:
                field_id = uuid.UUID(field_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(CustomField).where(CustomField.id == field_id, CustomField.active_filter())
        )

    @classmethod
    def get_values_map(cls, module_code: str, entity_id: uuid.UUID) -> dict[str, str | None]:
        fields = cls.list_for_module(module_code, include_hidden=True)
        if not fields:
            return {}
        field_ids = [f.id for f in fields]
        rows = db.session.scalars(
            db.select(CustomFieldValue).where(
                CustomFieldValue.custom_field_id.in_(field_ids),
                CustomFieldValue.entity_type == module_code,
                CustomFieldValue.entity_id == entity_id,
                CustomFieldValue.active_filter(),
            )
        )
        by_field = {row.custom_field_id: row.value_text for row in rows}
        return {f.code: by_field.get(f.id) for f in fields}

    @classmethod
    def form_context(cls, module_code: str, entity_id: uuid.UUID | None = None) -> dict[str, Any]:
        fields = cls.list_for_module(module_code)
        values = cls.get_values_map(module_code, entity_id) if entity_id else {}
        return {
            "custom_fields": fields,
            "custom_field_values": values,
            "custom_field_module": module_code,
        }

    @classmethod
    def detail_context(cls, module_code: str, entity_id: uuid.UUID, user: User) -> dict[str, Any]:
        items = []
        values = cls.get_values_map(module_code, entity_id)
        for field in cls.list_for_module(module_code):
            if not user.can_view_field(module_code, field.code):
                continue
            raw = values.get(field.code)
            items.append({"field": field, "display": cls.format_display(field, raw)})
        return {"custom_field_details": items}

    @classmethod
    def format_display(cls, field: CustomField, raw: str | None) -> str:
        if raw is None or raw == "":
            return "—"
        if field.field_type == FIELD_TYPE_BOOLEAN:
            return "Да" if raw in ("1", "true", "True", "on", "yes") else "Нет"
        if field.field_type == FIELD_TYPE_SELECT:
            for opt in field.options:
                if opt.deleted_at is None and opt.value == raw:
                    return opt.label
        return raw

    @classmethod
    def _parse_submitted(cls, field: CustomField, raw: str | None) -> str | None:
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            if field.is_required:
                raise ValidationError(f"Поле «{field.name}» обязательно.")
            return None
        raw = raw.strip() if isinstance(raw, str) else str(raw)
        if field.field_type == FIELD_TYPE_NUMBER:
            try:
                Decimal(raw.replace(",", "."))
            except InvalidOperation as exc:
                raise ValidationError(f"«{field.name}»: укажите число.") from exc
        if field.field_type == FIELD_TYPE_SELECT:
            allowed = {o.value for o in field.options if o.deleted_at is None}
            if raw not in allowed:
                raise ValidationError(f"«{field.name}»: недопустимое значение.")
        if field.field_type == FIELD_TYPE_BOOLEAN:
            return "1" if raw in ("1", "true", "on", "yes") else "0"
        return raw

    @classmethod
    def validate_from_form(
        cls,
        module_code: str,
        form_data: ImmutableMultiDict,
        user: User,
    ) -> None:
        fields = cls.list_for_module(module_code, include_hidden=True)
        for field in fields:
            if not field.is_visible or not user.can_edit_field(module_code, field.code):
                continue
            form_key = field.form_name
            raw = form_data.get(form_key)
            if field.field_type == FIELD_TYPE_BOOLEAN and form_key not in form_data:
                raw = "0"
            cls._parse_submitted(field, raw)

    @classmethod
    def save_from_form(
        cls,
        module_code: str,
        entity_id: uuid.UUID,
        form_data: ImmutableMultiDict,
        user: User,
    ) -> None:
        cls.validate_from_form(module_code, form_data, user)
        fields = cls.list_for_module(module_code, include_hidden=True)
        for field in fields:
            if not field.is_visible:
                continue
            form_key = field.form_name
            if not user.can_edit_field(module_code, field.code):
                continue
            raw = form_data.get(form_key)
            if field.field_type == FIELD_TYPE_BOOLEAN and form_key not in form_data:
                raw = "0"
            value = cls._parse_submitted(field, raw)
            cls._upsert_value(field, module_code, entity_id, value, user.id)

        db.session.commit()

    @classmethod
    def _upsert_value(
        cls,
        field: CustomField,
        entity_type: str,
        entity_id: uuid.UUID,
        value: str | None,
        actor_id: uuid.UUID,
    ) -> None:
        existing = db.session.scalar(
            db.select(CustomFieldValue).where(
                CustomFieldValue.custom_field_id == field.id,
                CustomFieldValue.entity_type == entity_type,
                CustomFieldValue.entity_id == entity_id,
                CustomFieldValue.active_filter(),
            )
        )
        if value is None:
            if existing is not None:
                existing.soft_delete(deleted_by=actor_id)
            return
        if existing is None:
            db.session.add(
                CustomFieldValue(
                    custom_field_id=field.id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    value_text=value,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            existing.value_text = value
            existing.updated_by = actor_id

    @classmethod
    def custom_fields_dict(cls, module_code: str) -> dict[str, str]:
        return {f.code: f.name for f in cls.list_for_module(module_code, include_hidden=True)}

    @classmethod
    def search_hits(cls, query: str, user: User, *, limit: int = 20) -> list[dict]:
        from app.core.search import like_or, like_patterns

        patterns = like_patterns(query)
        stmt = (
            db.select(CustomFieldValue, CustomField, SystemModule)
            .join(CustomField, CustomFieldValue.custom_field_id == CustomField.id)
            .join(SystemModule, CustomField.module_id == SystemModule.id)
            .where(
                CustomFieldValue.active_filter(),
                CustomField.active_filter(),
                CustomField.is_visible.is_(True),
                like_or(CustomFieldValue.value_text, patterns=patterns),
            )
            .limit(limit * 3)
        )
        hits: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for val, field, mod in db.session.execute(stmt):
            perm = f"{mod.code}.view"
            if not user.has_permission(perm):
                continue
            key = (mod.code, str(val.entity_id))
            if key in seen:
                continue
            seen.add(key)
            url_tpl = ENTITY_URLS.get(mod.code, "/")
            hits.append(
                {
                    "id": str(val.entity_id),
                    "title": f"{field.name}: {cls.format_display(field, val.value_text)}",
                    "subtitle": f"{mod.name} · {field.name}",
                    "url": url_tpl.format(id=val.entity_id),
                    "rank": 0.8,
                    "meta": {"module": mod.code, "field": field.code},
                }
            )
            if len(hits) >= limit:
                break
        return hits