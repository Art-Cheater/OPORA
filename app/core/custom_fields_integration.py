"""Интеграция пользовательских полей в модули CRUD."""

from __future__ import annotations

import uuid

from app.core.custom_field_service import CustomFieldService


def custom_field_form_context(module_code: str, entity_id: uuid.UUID | None = None) -> dict:
    return CustomFieldService.form_context(module_code, entity_id)


def save_custom_fields(module_code: str, entity_id: uuid.UUID, form_data, user) -> None:
    CustomFieldService.save_from_form(module_code, entity_id, form_data, user)


def custom_field_detail_context(module_code: str, entity_id: uuid.UUID, user) -> dict:
    return CustomFieldService.detail_context(module_code, entity_id, user)
