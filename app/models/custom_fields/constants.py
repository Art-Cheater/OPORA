"""Типы пользовательских полей."""

from __future__ import annotations

FIELD_TYPE_TEXT = "text"
FIELD_TYPE_TEXTAREA = "textarea"
FIELD_TYPE_NUMBER = "number"
FIELD_TYPE_DATE = "date"
FIELD_TYPE_DATETIME = "datetime"
FIELD_TYPE_BOOLEAN = "boolean"
FIELD_TYPE_SELECT = "select"

FIELD_TYPES: tuple[str, ...] = (
    FIELD_TYPE_TEXT,
    FIELD_TYPE_TEXTAREA,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_DATE,
    FIELD_TYPE_DATETIME,
    FIELD_TYPE_BOOLEAN,
    FIELD_TYPE_SELECT,
)

FIELD_TYPE_LABELS: dict[str, str] = {
    FIELD_TYPE_TEXT: "Текст",
    FIELD_TYPE_TEXTAREA: "Большой текст",
    FIELD_TYPE_NUMBER: "Число",
    FIELD_TYPE_DATE: "Дата",
    FIELD_TYPE_DATETIME: "Дата и время",
    FIELD_TYPE_BOOLEAN: "Логическое значение",
    FIELD_TYPE_SELECT: "Выпадающий список",
}

# Модули, поддерживающие конструктор полей
CUSTOM_FIELD_MODULES: tuple[str, ...] = ("requests", "projects", "contracts", "users")

CUSTOM_FIELD_MODULE_LABELS: dict[str, str] = {
    "requests": "Заявки",
    "projects": "Проекты",
    "contracts": "Договоры",
    "users": "Сотрудники",
}
