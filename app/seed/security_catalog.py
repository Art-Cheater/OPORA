"""Каталог модулей, полей, должностей и разрешений для seed."""

from __future__ import annotations

# (code, name, icon, sort_order, description)
SYSTEM_MODULES = [
    ("requests", "Заявки", "clipboard-check", 10, "Управление заявками"),
    ("projects", "Проекты", "folder2-open", 20, "Управление проектами"),
    ("contracts", "Договоры", "file-earmark-text", 30, "Управление договорами"),
    ("users", "Сотрудники", "people", 40, "Управление сотрудниками"),
    ("materials", "Материалы", "box-seam", 50, "Склад и материалы"),
    ("reports", "Отчёты", "bar-chart", 60, "Отчётность"),
    ("messenger", "Мессенджер", "chat-dots", 70, "Корпоративный мессенджер"),
    ("audit", "Журнал действий", "journal-text", 80, "Аудит системы"),
    ("roles", "Роли", "shield-lock", 90, "Управление ролями"),
    ("profile", "Профиль", "person", 100, "Личный профиль"),
    ("auth", "Безопасность", "shield-check", 110, "Журнал входов"),
    ("search", "Поиск", "search", 120, "Глобальный поиск"),
]

# module_code -> [(field_code, field_name, sort_order)]
MODULE_FIELDS: dict[str, list[tuple[str, str, int]]] = {
    "requests": [
        ("number", "Номер", 10),
        ("address", "Адрес", 20),
        ("pp", "ПП (пункт питания)", 30),
        ("received_at", "Дата и время получения", 40),
        ("dispatcher_name", "Диспетчер", 50),
        ("description", "Описание", 70),
        ("phone", "Телефон", 80),
        ("applicant_name", "Заявитель", 90),
        ("has_barrier", "Шлагбаум", 95),
        ("barrier_phone", "Телефон шлагбаума", 96),
        ("priority", "Приоритет", 100),
        ("status_id", "Статус", 130),
        ("created_at", "Дата создания", 150),
        # Скрыты в UI (остаются в БД): responsible_id, executor_id, latitude, longitude
        ("responsible_id", "Районный мастер", 900),
        ("executor_id", "Исполнитель", 910),
        ("latitude", "Широта", 920),
        ("longitude", "Долгота", 930),
    ],
    "projects": [
        ("code", "Код", 10),
        ("name", "Название", 20),
        ("description", "Описание", 30),
        ("status", "Статус", 40),
        ("progress_percent", "Готовность", 50),
        ("start_date", "Дата начала", 60),
        ("end_date", "Дата окончания", 70),
        ("responsible_id", "Ответственный", 80),
        ("executor_ids", "Исполнители", 90),
    ],
    "contracts": [
        ("contract_type", "Тип", 10),
        ("number", "Номер", 20),
        ("title", "Название", 30),
        ("description", "Описание", 40),
        ("status", "Статус", 50),
        ("contract_date", "Дата", 60),
        ("responsible_id", "Ответственный", 70),
    ],
    "users": [
        ("full_name", "ФИО", 10),
        ("email", "Email", 20),
        ("phone", "Телефон", 30),
        ("position_id", "Должность", 40),
        ("department", "Подразделение", 50),
        ("role_ids", "Роли", 60),
        ("password", "Пароль", 70),
    ],
}

# (code, name, sort_order)
POSITIONS = [
    ("director", "Директор", 10),
    ("deputy_director", "Заместитель директора", 20),
    ("dispatcher", "Диспетчер", 30),
    ("master", "Мастер", 40),
    ("emergency_team", "Аварийная бригада", 50),
    ("engineer", "Инженер", 60),
    ("electrician", "Электромонтер", 70),
    ("accountant", "Бухгалтер", 80),
    ("employee", "Сотрудник", 90),
]

# ФИО диспетчеров для выбора в заявке (общий аккаунт → кто принял)
# Можно править список здесь и перезапустить seed-reference-data
REQUEST_DISPATCHERS: list[tuple[str, int]] = [
    ("Иванова А.С.", 10),
    ("Петрова М.В.", 20),
    ("Сидоров К.Н.", 30),
    ("Козлова Е.И.", 40),
]

# Модули с полным набором действий
FULL_ACTION_MODULES = (
    "requests",
    "projects",
    "contracts",
    "users",
    "materials",
    "reports",
)

# Специальные права (module, action, name)
SPECIAL_PERMISSIONS = [
    ("audit", "view", "Просмотр журнала действий"),
    ("audit", "export", "Экспорт журнала действий"),
    ("roles", "view", "Просмотр ролей"),
    ("roles", "manage", "Управление ролями"),
    ("profile", "view", "Просмотр профиля"),
    ("profile", "edit", "Редактирование профиля"),
    ("auth", "login_logs.view", "Просмотр журнала входов"),
    ("messenger", "use", "Использование мессенджера"),
    ("search", "use", "Глобальный поиск"),
    ("users", "block", "Блокировка пользователей"),
    ("requests", "approve", "Одобрение заявок"),
    ("requests", "dispatch", "Диспетчеризация заявок"),
]

ACTION_LABELS = {
    "view": "Просмотр",
    "create": "Создание",
    "edit": "Редактирование",
    "delete": "Удаление",
    "export": "Экспорт",
    "print": "Печать",
    "status_change": "Изменение статуса",
    "file_upload": "Загрузка файлов",
    "file_delete": "Удаление файлов",
    "manage": "Управление",
    "use": "Использование",
    "block": "Блокировка",
    "approve": "Одобрение",
    "dispatch": "Диспетчеризация",
    "login_logs.view": "Просмотр журнала входов",
}

STANDARD_ACTIONS = (
    "view",
    "create",
    "edit",
    "delete",
    "export",
    "print",
    "status_change",
    "file_upload",
    "file_delete",
)

def build_permission_catalog() -> list[tuple[str, str, str, str]]:
    """(code, name, module, action)."""
    catalog: list[tuple[str, str, str, str]] = []
    module_names = {m[0]: m[1] for m in SYSTEM_MODULES}

    for module_code in FULL_ACTION_MODULES:
        mod_name = module_names.get(module_code, module_code)
        for action in STANDARD_ACTIONS:
            label = ACTION_LABELS.get(action, action)
            catalog.append((f"{module_code}.{action}", f"{mod_name}: {label}", module_code, action))

    for module_code, action, name in SPECIAL_PERMISSIONS:
        catalog.append((f"{module_code}.{action}", name, module_code, action))

    return catalog
