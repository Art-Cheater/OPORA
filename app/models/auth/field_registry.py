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
        "original_address": "Исходный адрес",
        "normalized_address": "Нормализованный адрес",
        "region": "Регион адреса",
        "district": "Район",
        "settlement": "Населённый пункт",
        "street": "Улица",
        "house": "Дом",
        "address_source": "Источник адреса",
        "address_external_id": "Внешний ID адреса",
        "latitude": "Широта",
        "longitude": "Долгота",
        "phone": "Телефон",
        "applicant_name": "Заявитель",
        "has_barrier": "Шлагбаум",
        "barrier_phone": "Телефон шлагбаума",
        "for_beresnev": "Для Береснева",
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
        "end_date": "Дата окончания",
        "contractor_name": "Подрядчик",
        "amount": "Сумма",
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
            return {mod: dict(items) for mod, items in fields.items()}
    except Exception:
        pass
    return {mod: dict(items) for mod, items in _FALLBACK_MODULE_FIELDS.items()}


def module_labels() -> dict[str, str]:
    return get_module_labels()


def module_fields() -> dict[str, dict[str, str]]:
    return get_module_fields()


# Не дергаем БД на импорте модуля — каталог читается при первом запросе.
MODULE_LABELS = dict(_FALLBACK_MODULE_LABELS)
MODULE_FIELDS = {mod: dict(items) for mod, items in _FALLBACK_MODULE_FIELDS.items()}
