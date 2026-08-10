"""Реестр полей модулей — загрузка из БД с fallback."""

from __future__ import annotations

from app.core.field_catalog import catalog_fields_dict
from app.core.permission_service import PermissionService

_FALLBACK_MODULE_LABELS: dict[str, str] = {
    "requests": "Заявки",
    "projects": "Проекты",
    "contracts": "Договоры",
    "users": "Сотрудники",
}

_FALLBACK_MODULE_FIELDS: dict[str, dict[str, str]] = {
    "requests": {
        "number": "Номер",
        "title": "Название",
        "description": "Описание",
        "address": "Адрес",
        "latitude": "Широта",
        "longitude": "Долгота",
        "phone": "Телефон",
        "applicant_name": "ФИО заявителя",
        "priority": "Приоритет",
        "status_id": "Статус",
        "responsible_id": "Ответственный",
        "executor_id": "Исполнитель",
        "created_at": "Дата создания",
    },
    "projects": {
        "code": "Код",
        "name": "Название",
        "description": "Описание",
        "status": "Статус",
        "progress_percent": "Готовность",
        "start_date": "Дата начала",
        "end_date": "Дата окончания",
        "responsible_id": "Ответственный",
        "executor_ids": "Исполнители",
    },
    "contracts": {
        "contract_type": "Тип",
        "number": "Номер",
        "title": "Название",
        "description": "Описание",
        "status": "Статус",
        "contract_date": "Дата",
        "responsible_id": "Ответственный",
    },
    "users": {
        "full_name": "ФИО",
        "email": "Email",
        "phone": "Телефон",
        "position_id": "Должность",
        "department": "Подразделение",
        "role_ids": "Роли",
        "password": "Пароль",
    },
}


def get_module_labels() -> dict[str, str]:
    try:
        labels = PermissionService.module_labels()
        if labels:
            return labels
    except Exception:
        pass
    return dict(_FALLBACK_MODULE_LABELS)


def get_module_fields() -> dict[str, dict[str, str]]:
    try:
        fields = catalog_fields_dict()
        if fields:
            return fields
    except Exception:
        pass
    return dict(_FALLBACK_MODULE_FIELDS)


def module_labels() -> dict[str, str]:
    return get_module_labels()


def module_fields() -> dict[str, dict[str, str]]:
    return get_module_fields()


# Обратная совместимость для существующих импортов
MODULE_LABELS = get_module_labels()
MODULE_FIELDS = get_module_fields()
