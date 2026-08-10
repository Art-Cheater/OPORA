"""Утилиты для форм и AJAX-ответов с ошибками валидации."""

from __future__ import annotations

from flask_wtf import FlaskForm


def form_errors_message(form: FlaskForm) -> str:
    """Человекочитаемое сообщение по ошибкам WTForms."""
    parts: list[str] = []
    for field_name, errors in form.errors.items():
        if field_name == "csrf_token":
            continue
        field = getattr(form, field_name, None)
        label = field.label.text if field is not None and hasattr(field, "label") else field_name
        for error in errors:
            parts.append(f"{label}: {error}")
    if parts:
        return "Исправьте ошибки: " + "; ".join(parts)
    return "Проверьте корректность заполнения полей."


def form_errors_dict(form: FlaskForm) -> dict[str, list[str]]:
    """Словарь ошибок полей для JSON-ответа."""
    return {k: list(v) for k, v in form.errors.items() if k != "csrf_token"}
