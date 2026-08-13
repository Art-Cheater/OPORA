"""Настройки встроенных полей модулей (название, порядок, видимость)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from wtforms.validators import DataRequired, InputRequired, Optional

from app.core.exceptions import ValidationError
from app.core.permission_service import PermissionService
from app.extensions import db
from app.models.auth.field_definition import FieldDefinition
from app.models.auth.system_module import SystemModule
from app.models.base import utcnow


@dataclass(frozen=True, slots=True)
class BuiltinFieldSettings:
    id: uuid.UUID
    code: str
    name: str
    sort_order: int
    is_visible: bool


class BuiltinFieldService:
    """CRUD метаданных встроенных полей (без удаления колонок БД)."""

    @staticmethod
    @lru_cache(maxsize=64)
    def get_settings(module_code: str) -> dict[str, BuiltinFieldSettings]:
        rows = db.session.scalars(
            db.select(FieldDefinition)
            .join(SystemModule, FieldDefinition.module_id == SystemModule.id)
            .where(
                SystemModule.code == module_code,
                SystemModule.active_filter(),
                FieldDefinition.active_filter(),
                FieldDefinition.is_active.is_(True),
            )
            .order_by(FieldDefinition.sort_order.asc(), FieldDefinition.name.asc())
        ).all()
        return {
            row.code: BuiltinFieldSettings(
                id=row.id,
                code=row.code,
                name=row.name,
                sort_order=row.sort_order,
                is_visible=bool(row.is_visible),
            )
            for row in rows
        }

    @classmethod
    def clear_cache(cls) -> None:
        cls.get_settings.cache_clear()

    @classmethod
    def is_visible(cls, module_code: str, field_code: str) -> bool:
        settings = cls.get_settings(module_code)
        meta = settings.get(field_code)
        if meta is None:
            # Нет в каталоге — считаем видимым (не ломаем сторонние поля форм)
            return True
        return meta.is_visible

    @classmethod
    def label(cls, module_code: str, field_code: str, fallback: str | None = None) -> str:
        meta = cls.get_settings(module_code).get(field_code)
        if meta is not None:
            return meta.name
        return fallback or field_code

    @classmethod
    def get_by_id(cls, field_id: uuid.UUID) -> FieldDefinition | None:
        return db.session.scalar(
            db.select(FieldDefinition).where(
                FieldDefinition.id == field_id,
                FieldDefinition.active_filter(),
            )
        )

    @classmethod
    def update_field(
        cls,
        field: FieldDefinition,
        *,
        name: str,
        sort_order: int,
        is_visible: bool,
        actor_id: uuid.UUID | None = None,
    ) -> FieldDefinition:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Укажите название поля.")
        if len(name) > 150:
            raise ValidationError("Название слишком длинное.")

        field.name = name
        field.sort_order = int(sort_order or 0)
        # Скрытое поле всегда необязательно в UI
        field.is_visible = bool(is_visible)
        field.updated_at = utcnow()
        if actor_id is not None:
            field.updated_by = actor_id
        db.session.commit()
        cls.clear_cache()
        PermissionService.clear_cache()
        return field

    @classmethod
    def hide_field(cls, field: FieldDefinition, actor_id: uuid.UUID | None = None) -> FieldDefinition:
        return cls.update_field(
            field,
            name=field.name,
            sort_order=field.sort_order,
            is_visible=False,
            actor_id=actor_id,
        )

    @classmethod
    def apply_to_form(cls, form, module_code: str) -> None:
        """Подписи из каталога; у скрытых полей снимает DataRequired."""
        settings = cls.get_settings(module_code)
        for code, meta in settings.items():
            if not hasattr(form, code):
                continue
            field = getattr(form, code)
            if hasattr(field, "label") and field.label is not None:
                field.label.text = meta.name
            if not meta.is_visible:
                field.validators = [
                    v
                    for v in list(field.validators)
                    if not isinstance(v, (DataRequired, InputRequired))
                ]
                if not any(isinstance(v, Optional) for v in field.validators):
                    field.validators.insert(0, Optional())
                if hasattr(field.flags, "required"):
                    field.flags.required = False

    @classmethod
    def value_or_default(
        cls,
        module_code: str,
        field_code: str,
        submitted,
        *,
        default=None,
        entity=None,
        attr: str | None = None,
    ):
        """
        Если поле скрыто и submitted пустой — берём значение сущности (edit)
        или default (create).
        """
        if cls.is_visible(module_code, field_code):
            return submitted

        empty = submitted is None or submitted == ""
        if not empty:
            return submitted

        attr_name = attr or field_code
        if entity is not None and hasattr(entity, attr_name):
            return getattr(entity, attr_name)
        return default
