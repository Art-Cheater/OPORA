"""Константы путевых листов."""

from __future__ import annotations

STATUS_DRAFT = "draft"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

WAYBILL_STATUSES = (
    (STATUS_DRAFT, "Черновик"),
    (STATUS_IN_PROGRESS, "В работе"),
    (STATUS_COMPLETED, "Выполнен"),
    (STATUS_CANCELLED, "Отменён"),
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_DRAFT: frozenset({STATUS_IN_PROGRESS, STATUS_CANCELLED}),
    STATUS_IN_PROGRESS: frozenset({STATUS_COMPLETED, STATUS_CANCELLED}),
    STATUS_COMPLETED: frozenset(),
    STATUS_CANCELLED: frozenset(),
}

ROW_STATUS_CLASS = {
    STATUS_DRAFT: "table-row-draft",
    STATUS_IN_PROGRESS: "table-row-brigade",
    STATUS_COMPLETED: "table-row-done",
    STATUS_CANCELLED: "table-row-cancelled",
}

WAYBILL_STATUS_LABELS = {code: name for code, name in WAYBILL_STATUSES}


def can_transition(from_code: str, to_code: str) -> bool:
    return to_code in ALLOWED_TRANSITIONS.get(from_code, frozenset())


def status_label(code: str | None) -> str:
    return WAYBILL_STATUS_LABELS.get(code or "", code or "—")


def row_status_class(status_code: str | None) -> str:
    return ROW_STATUS_CLASS.get(status_code or "", "table-row-draft")
