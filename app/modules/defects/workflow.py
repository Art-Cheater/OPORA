"""Константы дефектов."""

from __future__ import annotations

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_FIXED = "fixed"
STATUS_CANCELLED = "cancelled"

DEFECT_STATUSES = (
    (STATUS_OPEN, "Открыт", "Обнаружен, требует внимания", "#DC3545", 10, False),
    (STATUS_IN_PROGRESS, "В работе", "Устранён или устраняется", "#E6A700", 20, False),
    (STATUS_FIXED, "Устранён", "Дефект закрыт", "#2E7D32", 30, True),
    (STATUS_CANCELLED, "Отменён", "Дефект снят", "#78909C", 40, True),
)

DEFECT_CATEGORIES = (
    ("lighting", "Освещение", 10),
    ("pole", "Опора", 20),
    ("cable", "Кабель", 30),
    ("cabinet", "ШУНО", 40),
    ("other", "Иное", 50),
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_OPEN: frozenset({STATUS_IN_PROGRESS, STATUS_FIXED, STATUS_CANCELLED}),
    STATUS_IN_PROGRESS: frozenset({STATUS_FIXED, STATUS_CANCELLED}),
    STATUS_FIXED: frozenset(),
    STATUS_CANCELLED: frozenset(),
}

ROW_STATUS_CLASS = {
    STATUS_OPEN: "table-row-new",
    STATUS_IN_PROGRESS: "table-row-brigade",
    STATUS_FIXED: "table-row-done",
    STATUS_CANCELLED: "table-row-cancelled",
}


def can_transition(from_code: str, to_code: str) -> bool:
    return to_code in ALLOWED_TRANSITIONS.get(from_code, frozenset())


def row_status_class(status_code: str | None) -> str:
    return ROW_STATUS_CLASS.get(status_code or "", "table-row-draft")
