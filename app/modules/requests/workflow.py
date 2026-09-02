"""Машина состояний и действия workflow заявок.

Жизненный цикл (время жизни заявки):
  Новая
    → Выехала аварийная бригада  (строка жёлтая)
    → Передана мастеру           (строка жёлтая)
    → Выполнено                  (строка зелёная)
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

# Коды статусов рабочего процесса
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

# Этапы «времени жизни» для UI (без отмены)
LIFECYCLE_STEPS = (
    (STATUS_NEW, "Новая"),
    (STATUS_EMERGENCY_DISPATCHED, "Выехала бригада"),
    (STATUS_ACCEPTED_BY_MASTER, "Передана мастеру"),
    (STATUS_COMPLETED, "Выполнено"),
)

# Допустимые переходы
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    # С «Новая» можно сразу передать мастеру, минуя бригаду
    STATUS_NEW: frozenset(
        {STATUS_EMERGENCY_DISPATCHED, STATUS_ACCEPTED_BY_MASTER, STATUS_CANCELLED}
    ),
    STATUS_EMERGENCY_DISPATCHED: frozenset({STATUS_ACCEPTED_BY_MASTER, STATUS_CANCELLED}),
    # Мастер сразу отмечает «Выполнено»; «В работе» — опционально
    STATUS_ACCEPTED_BY_MASTER: frozenset(
        {STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_CANCELLED}
    ),
    STATUS_IN_PROGRESS: frozenset({STATUS_COMPLETED, STATUS_CANCELLED}),
    STATUS_COMPLETED: frozenset(),
    STATUS_CANCELLED: frozenset(),
}

# CSS-класс строки списка по статусу
ROW_STATUS_CLASS = {
    STATUS_NEW: "table-row-new",
    STATUS_EMERGENCY_DISPATCHED: "table-row-brigade",
    STATUS_ACCEPTED_BY_MASTER: "table-row-brigade",
    STATUS_IN_PROGRESS: "table-row-brigade",
    STATUS_COMPLETED: "table-row-done",
    STATUS_CANCELLED: "table-row-cancelled",
}

# Действия истории
HISTORY_EMERGENCY_DEPARTED = "emergency_departed"
HISTORY_ASSIGN_MASTER = "assign_master"
HISTORY_ACCEPT_MASTER = "accept_master"
HISTORY_START_WORK = "start_work"
HISTORY_COMPLETE = "complete"
HISTORY_CANCEL = "cancel"
HISTORY_STATUS_CHANGE = "status_change"
# устаревшее (оставлено для старых записей истории)
HISTORY_DISPATCH_EMERGENCY = "dispatch_emergency"

# Пресеты фильтров списка
PRESET_AWAITING_MASTER = "awaiting_master"
PRESET_MY = "my"
PRESET_IN_PROGRESS = "in_progress"
PRESET_COMPLETED = "completed"
PRESET_FOR_EMERGENCY = "for_emergency"


@dataclass(frozen=True)
class WorkflowAction:
    """Описание доступного действия в карточке заявки."""

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
    """Этапы времени жизни для карточки заявки."""
    order = [code for code, _ in LIFECYCLE_STEPS]
    # «В работе» считаем как этап «Передана мастеру»
    current = status_code or STATUS_NEW
    if current == STATUS_IN_PROGRESS:
        current = STATUS_ACCEPTED_BY_MASTER
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
    """Действия по текущему статусу и правам."""
    if req.status is None or req.deleted_at is not None:
        return []

    code = req.status.code
    actions: list[WorkflowAction] = []
    has_dispatch = user.has_permission(PERM_REQUESTS_DISPATCH)
    has_approve = user.has_permission(PERM_REQUESTS_APPROVE)
    has_edit = user.has_permission(PERM_REQUESTS_EDIT)

    if code == STATUS_NEW:
        if has_dispatch:
            actions.append(
                WorkflowAction(
                    code="mark_emergency_departed",
                    label="Выехала аварийная бригада",
                    endpoint="requests.mark_emergency_departed",
                    style="warning",
                    confirm="Подтвердить выезд аварийной бригады?",
                )
            )
            actions.append(
                WorkflowAction(
                    code="assign_master",
                    label="Передать мастеру",
                    endpoint="requests.assign_master",
                    style="primary",
                    needs_master=True,
                )
            )
            actions.append(
                WorkflowAction(
                    code="cancel",
                    label="Отменить заявку",
                    endpoint="requests.cancel_request",
                    style="outline-secondary",
                    confirm="Отменить заявку?",
                )
            )

    elif code == STATUS_EMERGENCY_DISPATCHED:
        if has_dispatch:
            actions.append(
                WorkflowAction(
                    code="assign_master",
                    label="Передать мастеру",
                    endpoint="requests.assign_master",
                    style="primary",
                    needs_master=True,
                )
            )
        # Альтернатива: мастер принимает заявку сам
        if has_approve and req.responsible_id is None:
            actions.append(
                WorkflowAction(
                    code="accept",
                    label="Принять заявку",
                    endpoint="requests.accept_request",
                    style="primary",
                    confirm="Принять заявку на себя?",
                )
            )
        if has_dispatch:
            actions.append(
                WorkflowAction(
                    code="cancel",
                    label="Отменить заявку",
                    endpoint="requests.cancel_request",
                    style="outline-secondary",
                    confirm="Отменить заявку?",
                )
            )

    elif code == STATUS_ACCEPTED_BY_MASTER:
        if has_approve:
            actions.append(
                WorkflowAction(
                    code="start_work",
                    label="Начать работу",
                    endpoint="requests.start_work",
                    style="primary",
                    confirm="Отметить начало работ?",
                )
            )
        if has_approve or has_edit:
            actions.append(
                WorkflowAction(
                    code="complete",
                    label="Выполнено",
                    endpoint="requests.complete_request",
                    style="success",
                    confirm="Отметить заявку как выполненную?",
                )
            )
        if has_dispatch:
            actions.append(
                WorkflowAction(
                    code="cancel",
                    label="Отменить заявку",
                    endpoint="requests.cancel_request",
                    style="outline-secondary",
                    confirm="Отменить заявку?",
                )
            )

    elif code == STATUS_IN_PROGRESS:
        if has_approve or has_edit:
            actions.append(
                WorkflowAction(
                    code="complete",
                    label="Выполнено",
                    endpoint="requests.complete_request",
                    style="success",
                    confirm="Отметить заявку как выполненную?",
                )
            )
        if has_dispatch:
            actions.append(
                WorkflowAction(
                    code="cancel",
                    label="Отменить заявку",
                    endpoint="requests.cancel_request",
                    style="outline-secondary",
                    confirm="Отменить заявку?",
                )
            )

    return actions