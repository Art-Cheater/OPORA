"""Проверки машины переходов статусов заявок (без БД)."""

from app.modules.requests.workflow import (
    STATUS_ACCEPTED_BY_MASTER,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_EMERGENCY_DISPATCHED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    available_actions,
    can_transition,
    lifecycle_progress,
)


class _User:
    def __init__(self, *perms):
        self._perms = set(perms)

    def has_permission(self, code):
        return code in self._perms


class _Status:
    def __init__(self, code):
        self.code = code


class _Request:
    def __init__(self, code):
        self.status = _Status(code)
        self.deleted_at = None


def test_happy_path_transitions():
    assert can_transition(STATUS_NEW, STATUS_COMPLETED)
    assert can_transition(STATUS_EMERGENCY_DISPATCHED, STATUS_COMPLETED)
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
    assert not can_transition(STATUS_NEW, STATUS_ACCEPTED_BY_MASTER)
    assert not can_transition(STATUS_NEW, STATUS_EMERGENCY_DISPATCHED)
    assert can_transition(STATUS_NEW, STATUS_COMPLETED)
    assert not can_transition(STATUS_COMPLETED, STATUS_IN_PROGRESS)
    assert not can_transition(STATUS_CANCELLED, STATUS_NEW)
    assert can_transition(STATUS_EMERGENCY_DISPATCHED, STATUS_COMPLETED)


def test_ui_actions_only_complete():
    user = _User("requests.edit")
    actions = available_actions(_Request(STATUS_NEW), user)
    assert [a.code for a in actions] == ["complete"]
    assert all(not a.needs_master for a in actions)
    labels = " ".join(a.label for a in actions)
    assert "Выполнено" in labels
    assert "мастеру" not in labels.lower()
    assert "бригад" not in labels.lower()
    assert available_actions(_Request(STATUS_COMPLETED), user) == []


def test_lifecycle_is_new_then_completed():
    steps = lifecycle_progress(STATUS_NEW)
    assert [s["code"] for s in steps] == [STATUS_NEW, STATUS_COMPLETED]
    old = lifecycle_progress(STATUS_ACCEPTED_BY_MASTER)
    assert old[0]["state"] == "current"
    done = lifecycle_progress(STATUS_COMPLETED)
    assert done[-1]["state"] == "current"
