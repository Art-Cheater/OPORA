"""Полная очистка заявок."""

from app.extensions import db
from app.models.auth.user import User
from app.models.requests.request import Request
from app.modules.requests.services import RequestService


def test_wipe_all_removes_requests(admin_client, app):
    created = admin_client.post(
        "/requests/new",
        data={
            "number": "WIPE-1",
            "address": "ул. Очистка, 1",
            "received_at": "2026-08-21T12:00",
            "dispatcher_name": "Иванова А.С.",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302, created.get_data(as_text=True)[:1500]

    with app.app_context():
        actor = db.session.scalar(db.select(User.id).where(User.email == "admin@opora.ru"))
        assert db.session.scalar(db.select(db.func.count()).select_from(Request)) >= 1
        removed = RequestService.wipe_all(actor)
        assert removed >= 1
        assert db.session.scalar(db.select(db.func.count()).select_from(Request)) == 0
