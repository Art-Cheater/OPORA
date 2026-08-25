"""Фильтры заявок: район, ПП, «Для Береснева»."""

from __future__ import annotations

import uuid

from app.extensions import db
from app.models.requests.request import Request
from app.modules.requests.districts import normalize_request_district


def _login(client, email: str = "admin@opora.ru", password: str = "admin123"):
    client.get("/auth/logout", follow_redirects=True)
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def _create_request(admin_client, *, district: str, pp: str, for_beresnev: bool = False) -> str:
    number = f"O-{uuid.uuid4().hex[:8].upper()}"
    data = {
        "number": number,
        "address": f"Лепсе {uuid.uuid4().hex[:4]}",
        "district": district,
        "pp": pp,
        "received_at": "2026-08-13T10:00",
        "dispatcher_name": "Иванова А.С.",
        "applicant_name": "Тест",
        "priority": "medium",
        "submit": "Сохранить",
    }
    if for_beresnev:
        data["for_beresnev"] = "y"
    resp = admin_client.post("/requests/new", data=data, follow_redirects=False)
    assert resp.status_code == 302, resp.get_data(as_text=True)[:2000]
    return resp.headers["Location"].rstrip("/").split("/")[-1]


def test_normalize_request_district():
    assert normalize_request_district("Ленинский район") == "Ленинский"
    assert normalize_request_district("октябрьский") == "Октябрьский"
    assert normalize_request_district("") is None


def test_request_filters_district_pp_beresnev(admin_client, app):
    _login(admin_client)
    target_id = _create_request(
        admin_client, district="Ленинский", pp="ТП-77", for_beresnev=True
    )
    other_id = _create_request(
        admin_client, district="Октябрьский", pp="ТП-11", for_beresnev=False
    )

    with app.app_context():
        target = db.session.get(Request, uuid.UUID(target_id))
        other = db.session.get(Request, uuid.UUID(other_id))
        assert target is not None and other is not None
        assert target.for_beresnev is True
        assert other.for_beresnev is False
        assert target.district == "Ленинский"

    page = admin_client.get("/requests/")
    html = page.get_data(as_text=True)
    assert "Поиск" in html
    assert 'name="district"' in html
    assert 'name="pp"' in html
    assert "Для Береснева" in html

    by_district = admin_client.get("/requests/table?district=Ленинский")
    assert by_district.status_code == 200
    district_html = by_district.get_json()["table_html"]
    assert target_id in district_html
    assert other_id not in district_html

    by_pp = admin_client.get("/requests/table?pp=ТП-77")
    assert by_pp.status_code == 200
    pp_html = by_pp.get_json()["table_html"]
    assert target_id in pp_html
    assert other_id not in pp_html

    by_flag = admin_client.get("/requests/table?for_beresnev=1")
    assert by_flag.status_code == 200
    flag_html = by_flag.get_json()["table_html"]
    assert target_id in flag_html
    assert other_id not in flag_html
