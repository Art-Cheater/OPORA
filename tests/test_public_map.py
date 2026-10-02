"""Публичная карта отдаёт только открытые заявки и не содержит личных данных."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.enums import Priority
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.repositories import RequestRepository


def test_public_map_returns_open_requests_without_personal_data(client, app):
    secret_name = "СекретныйЗаявитель"
    secret_phone = "+7 912 345-67-89"
    secret_text = "перезвоните Петрову, секретный комментарий"
    with app.app_context():
        journal_id = RequestRepository.get_default_journal().id
        statuses = {
            item.code: item
            for item in db.session.scalars(db.select(RequestStatus))
        }
        open_item = Request(
            number="26-7701",
            title=secret_text,
            description=f"{secret_text} {secret_phone}",
            address=f"ул. Ленина, 10, кв. 5, {secret_phone}",
            street="улица Ленина",
            house="10",
            district="Октябрьский",
            applicant_name=secret_name,
            phone=secret_phone,
            priority=Priority.MEDIUM.value,
            status_id=statuses["new"].id,
            journal_id=journal_id,
            latitude=Decimal("58.60359555"),
            longitude=Decimal("49.66801234"),
        )
        pasted = Request(
            number="26-7702",
            title=secret_text,
            address=f"Советская 5, кв. 12, {secret_phone}",
            applicant_name=secret_name,
            phone=secret_phone,
            priority=Priority.MEDIUM.value,
            status_id=statuses["in_progress"].id,
            journal_id=journal_id,
        )
        closed = Request(
            number="26-7703",
            title="Выполненная скрытая",
            address="СкрытаяВыполненная 1",
            applicant_name=secret_name,
            phone=secret_phone,
            priority=Priority.MEDIUM.value,
            status_id=statuses["completed"].id,
            journal_id=journal_id,
            latitude=Decimal("58.60"),
            longitude=Decimal("49.66"),
        )
        cancelled = Request(
            number="26-7704",
            title="Отменённая скрытая",
            address="СкрытаяОтменённая 2",
            applicant_name=secret_name,
            phone=secret_phone,
            priority=Priority.MEDIUM.value,
            status_id=statuses["cancelled"].id,
            journal_id=journal_id,
            latitude=Decimal("58.61"),
            longitude=Decimal("49.67"),
        )
        deleted = Request(
            number="26-7705",
            title=secret_text,
            address="УдалённаяУлица 3",
            applicant_name=secret_name,
            phone=secret_phone,
            priority=Priority.MEDIUM.value,
            status_id=statuses["new"].id,
            journal_id=journal_id,
            latitude=Decimal("58.62"),
            longitude=Decimal("49.68"),
        )
        deleted.soft_delete()
        db.session.add_all([open_item, pasted, closed, cancelled, deleted])
        db.session.commit()
        open_id = str(open_item.id)

    response = client.get("/public/kirovsvet/map.json")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=30"
    assert "Set-Cookie" not in response.headers
    body = response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["ok"] is True
    by_address = {item["address"]: item for item in payload["items"]}
    assert by_address["улица Ленина, 10"]["status"] == "Новая"
    assert by_address["улица Ленина, 10"]["district"] == "Октябрьский"
    assert by_address["улица Ленина, 10"]["lat"] == 58.6036
    assert by_address["улица Ленина, 10"]["lon"] == 49.66801
    assert by_address["Советская 5"]["status"] == "В работе"
    assert "lat" not in by_address["Советская 5"]
    for item in payload["items"]:
        assert set(item) <= {"address", "status", "district", "lat", "lon"}
    for hidden in (
        secret_name,
        secret_phone,
        "912",
        secret_text,
        "26-7701",
        "26-7703",
        "СкрытаяВыполненная",
        "СкрытаяОтменённая",
        "УдалённаяУлица",
        "кв.",
        open_id,
    ):
        assert hidden not in body

    foreign = client.get("/public/kirovsvet/map.json", headers={"Host": "opora.truthqwark.ru"})
    assert foreign.status_code == 404
    assert secret_name not in foreign.get_data(as_text=True)
