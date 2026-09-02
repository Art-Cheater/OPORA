"""Машина состояний и действия workflow заявок.

Пользовательский сценарий: Новая → Выполнено.
Старые статусы бригады/мастера остаются в БД для существующих записей.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.auth.constants import (
    PERM_REQUESTS_APPROVE,
    PERM_REQUESTS_DISPATCH,
    PERM_REQUESTS_EDIT,
)

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.requests.request import Request

STATUS_NEW = "new"
STATUS_EMERGENCY_DISPATCHED = "emergency_dispatched"
STATUS_ACCEPTED_BY_MASTER = "accepted_by_master"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

WORKFLOW_STATUS_CODES = (
    STATUS_NEW,
    STATUS_EMERGENCY_DISPATCHED,
    STATUS_ACCEPTED_BY_MASTER,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
)

OPEN_STATUS_CODES = frozenset(
    {
        STATUS_NEW,
        STATUS_EMERGENCY_DISPATCHED,
        STATUS_ACCEPTED_BY_MASTER,
        STATUS_IN_PROGRESS,
    }
)

LIFECYCLE_STEPS = (
    (STATUS_NEW, "Новая"),
    (STATUS_COMPLETED, "Выполнено"),
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_NEW: frozenset({STATUS_COMPLETED, STATUS_CANCELLED, STATUS_IN_PROGRESS}),
    STATUS_EMERGENCY_DISPATCHED: frozenset({STATUS_COMPLETED, STATUS_CANCELLED, STATUS_IN_PROGRESS}),
    STATUS_ACCEPTED_BY_MASTER: frozenset({STATUS_COMPLETED, STATUS_CANCELLED, STATUS_IN_PROGRESS}),
    STATUS_IN_PROGRESS: frozenset({STATUS_COMPLETED, STATUS_CANCELLED}),
    STATUS_COMPLETED: frozenset(),
    STATUS_CANCELLED: frozenset(),
}

ROW_STATUS_CLASS = {
    STATUS_NEW: "table-row-new",
    STATUS_EMERGENCY_DISPATCHED: "table-row-brigade",
    STATUS_ACCEPTED_BY_MASTER: "table-row-brigade",
    STATUS_IN_PROGRESS: "table-row-brigade",
    STATUS_COMPLETED: "table-row-done",
    STATUS_CANCELLED: "table-row-cancelled",
}

HISTORY_EMERGENCY_DEPARTED = "emergency_departed"
HISTORY_ASSIGN_MASTER = "assign_master"
HISTORY_ACCEPT_MASTER = "accept_master"
HISTORY_START_WORK = "start_work"
HISTORY_COMPLETE = "complete"
HISTORY_CANCEL = "cancel"
HISTORY_STATUS_CHANGE = "status_change"
HISTORY_DISPATCH_EMERGENCY = "dispatch_emergency"

PRESET_AWAITING_MASTER = "awaiting_master"
PRESET_MY = "my"
PRESET_IN_PROGRESS = "in_progress"
PRESET_COMPLETED = "completed"
PRESET_FOR_EMERGENCY = "for_emergency"


@dataclass(frozen=True)
class WorkflowAction:
    code: str
    label: str
    endpoint: str
    style: str = "primary"
    needs_master: bool = False
    confirm: str | None = None


def can_transition(from_code: str, to_code: str) -> bool:
    return to_code in ALLOWED_TRANSITIONS.get(from_code, frozenset())


def row_status_class(status_code: str | None) -> str:
    if not status_code:
        return ""
    return ROW_STATUS_CLASS.get(status_code, "")


def lifecycle_progress(status_code: str | None) -> list[dict]:
    current = status_code or STATUS_NEW
    if current in OPEN_STATUS_CODES:
        current = STATUS_NEW
    order = [code for code, _ in LIFECYCLE_STEPS]
    if current == STATUS_CANCELLED:
        current_idx = -1
    else:
        current_idx = order.index(current) if current in order else 0

    steps = []
    for idx, (code, label) in enumerate(LIFECYCLE_STEPS):
        if current == STATUS_CANCELLED:
            state = "pending"
        elif idx < current_idx:
            state = "done"
        elif idx == current_idx:
            state = "current"
        else:
            state = "pending"
        steps.append({"code": code, "label": label, "state": state})
    return steps


def available_actions(req: Request, user: User) -> list[WorkflowAction]:
    """Единственное пользовательское действие — «Выполнено»."""
    if req.status is None or req.deleted_at is not None:
        return []

    code = req.status.code
    if code not in OPEN_STATUS_CODES:
        return []

    has_dispatch = user.has_permission(PERM_REQUESTS_DISPATCH)
    has_approve = user.has_permission(PERM_REQUESTS_APPROVE)
    has_edit = user.has_permission(PERM_REQUESTS_EDIT)
    if not (has_dispatch or has_approve or has_edit):
        return []

    return [
        WorkflowAction(
            code="complete",
            label="Выполнено",
            endpoint="requests.complete_request",
            style="success",
            confirm="Отметить заявку как выполненную?",
        )
    ]
