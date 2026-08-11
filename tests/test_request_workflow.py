"""Проверки машины переходов статусов заявок (без БД)."""

from app.modules.requests.workflow import (
    STATUS_ACCEPTED_BY_MASTER,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_EMERGENCY_DISPATCHED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    can_transition,
)


def test_happy_path_transitions():
    assert can_transition(STATUS_NEW, STATUS_EMERGENCY_DISPATCHED)
    assert can_transition(STATUS_EMERGENCY_DISPATCHED, STATUS_ACCEPTED_BY_MASTER)
    assert can_transition(STATUS_ACCEPTED_BY_MASTER, STATUS_COMPLETED)
    assert can_transition(STATUS_IN_PROGRESS, STATUS_COMPLETED)


def test_cancel_allowed_from_active_statuses():
    for code in (
        STATUS_NEW,
        STATUS_EMERGENCY_DISPATCHED,
        STATUS_ACCEPTED_BY_MASTER,
        STATUS_IN_PROGRESS,
    ):
        assert can_transition(code, STATUS_CANCELLED)


def test_forbidden_transitions():
    assert can_transition(STATUS_NEW, STATUS_ACCEPTED_BY_MASTER)
    assert not can_transition(STATUS_NEW, STATUS_COMPLETED)
    assert not can_transition(STATUS_COMPLETED, STATUS_IN_PROGRESS)
    assert not can_transition(STATUS_CANCELLED, STATUS_NEW)
    assert not can_transition(STATUS_EMERGENCY_DISPATCHED, STATUS_COMPLETED)
