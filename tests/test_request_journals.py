"""Журналы заявок: нумерация внутри журнала."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import Priority
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.journals import JOURNAL_MAIN, JOURNAL_OKTYABRSKY_VILLAGES
from app.modules.requests.repositories import RequestRepository


def _status_new():
    return db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))


def _add_request(*, number: str, journal_id, address: str = "ул. Тест, 1") -> Request:
    req = Request(
        number=number,
        title=address,
        address=address,
        applicant_name="QA",
        priority=Priority.MEDIUM.value,
        status_id=_status_new().id,
        journal_id=journal_id,
    )
    db.session.add(req)
    db.session.commit()
    return req


def test_http_create_uses_default_journal(admin_client, app):
    resp = admin_client.post(
        "/requests/new",
        data={
            "number": "26-9001",
            "address": "Ленина 1",
            "received_at": "2026-09-02T10:00",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.get_data(as_text=True)[:500]
    request_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    with app.app_context():
        req = db.session.get(Request, request_id)
        journal = RequestRepository.get_default_journal()
        assert req is not None
        assert req.journal_id == journal.id
        assert journal.code == JOURNAL_MAIN


def test_same_number_allowed_in_two_journals(app):
    with app.app_context():
        main = RequestRepository.get_journal_by_code(JOURNAL_MAIN)
        villages = RequestRepository.get_journal_by_code(JOURNAL_OKTYABRSKY_VILLAGES)
        assert main is not None and villages is not None
        _add_request(number="26-15", journal_id=main.id, address="Город 1")
        other = _add_request(number="26-15", journal_id=villages.id, address="Деревня 1")
        assert other.number == "26-15"
        assert other.journal_id != main.id


def test_number_unique_inside_journal(app):
    with app.app_context():
        main = RequestRepository.get_default_journal()
        _add_request(number="26-77", journal_id=main.id)
        db.session.add(
            Request(
                number="26-77",
                title="Дубль",
                address="ул. Дубль",
                applicant_name="QA",
                priority=Priority.MEDIUM.value,
                status_id=_status_new().id,
                journal_id=main.id,
            )
        )
        try:
            db.session.flush()
            raised = False
        except IntegrityError:
            raised = True
            db.session.rollback()
        assert raised


def test_journals_filter_and_tabs(admin_client, app):
    page = admin_client.get("/requests/")
    html = page.get_data(as_text=True)
    assert "Все заявки" in html
    assert "Заявки в деревнях Октябрьского района" in html
    with app.app_context():
        journal = RequestRepository.get_journal_by_code(JOURNAL_OKTYABRSKY_VILLAGES)
        assert journal is not None
        journal_id = str(journal.id)
    table = admin_client.get(f"/requests/table?journal_id={journal_id}")
    assert table.status_code == 200
    assert "table_html" in table.get_json()
