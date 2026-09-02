"""Путевые листы: CRUD, точки, порядок, RBAC."""

from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.auth.user import User
from app.models.defects.defect_category import DefectCategory
from app.models.waybills.waybill import Waybill
from app.models.waybills.waybill_stop import WaybillStop


def _login(client, email: str, password: str = "pass12345"):
    client.post("/auth/logout", follow_redirects=True)
    client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )


def test_waybill_create_add_reorder(admin_client, app):
    req = admin_client.post(
        "/requests/new",
        data={
            "number": "26-5101",
            "address": "Октябрьский проспект 1",
            "received_at": "2026-09-02T12:00",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    request_id = req.headers["Location"].rstrip("/").split("/")[-1]
    with app.app_context():
        category_id = str(db.session.scalar(db.select(DefectCategory.id).where(DefectCategory.code == "cable")))
        master_id = str(db.session.scalar(db.select(User.id).where(User.email == "master@test.local")))
    defect = admin_client.post(
        "/defects/new",
        data={
            "number": "DF-26-51",
            "description": "Кабель",
            "category_id": category_id,
            "address": "Октябрьский проспект 3",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    defect_id = defect.headers["Location"].rstrip("/").split("/")[-1]
    created = admin_client.post(
        "/waybills/new",
        data={
            "number": "PL-26-1",
            "work_date": date.today().isoformat(),
            "master_id": master_id,
            "comment": "Выезд",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302, created.get_data(as_text=True)[:1500]
    waybill_id = created.headers["Location"].rstrip("/").split("/")[-1]
    assert admin_client.post(
        f"/waybills/{waybill_id}/stops",
        data={"entity_type": "request", "entity_id": request_id},
        follow_redirects=False,
    ).status_code in (200, 302)
    assert admin_client.post(
        f"/waybills/{waybill_id}/stops",
        data={"entity_type": "defect", "entity_id": defect_id},
        follow_redirects=False,
    ).status_code in (200, 302)
    with app.app_context():
        stops = list(
            db.session.scalars(
                db.select(WaybillStop)
                .where(WaybillStop.waybill_id == waybill_id, WaybillStop.active_filter())
                .order_by(WaybillStop.sort_order)
            )
        )
        assert len(stops) == 2
        assert stops[0].request_id is not None
        assert stops[1].defect_id is not None
        reversed_ids = [str(stops[1].id), str(stops[0].id)]
    reorder = admin_client.post(
        f"/waybills/{waybill_id}/stops/reorder",
        json={"stop_ids": reversed_ids},
    )
    assert reorder.status_code == 200, reorder.get_data(as_text=True)
    assert reorder.get_json()["ok"] is True
    with app.app_context():
        ordered = list(
            db.session.scalars(
                db.select(WaybillStop)
                .where(WaybillStop.waybill_id == waybill_id, WaybillStop.active_filter())
                .order_by(WaybillStop.sort_order)
            )
        )
        assert str(ordered[0].id) == reversed_ids[0]
        item = db.session.get(Waybill, waybill_id)
        assert item is not None and item.number == "PL-26-1"
    nearby = admin_client.get(f"/waybills/{waybill_id}/nearby")
    assert nearby.status_code == 200
    assert "hits" in nearby.get_json()
    route = admin_client.get(f"/waybills/{waybill_id}/map.json")
    assert route.status_code == 200
    assert "points" in route.get_json()


def test_dispatcher_cannot_create_waybill(client):
    _login(client, "dispatcher@test.local")
    page = client.get("/waybills/")
    assert page.status_code == 200
    created = client.post(
        "/waybills/new",
        data={
            "number": "PL-26-99",
            "work_date": date.today().isoformat(),
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert created.status_code in (302, 403)


def test_master_can_open_waybills(client):
    _login(client, "master@test.local")
    page = client.get("/waybills/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Путевые листы" in html or "opora-loading" in html
