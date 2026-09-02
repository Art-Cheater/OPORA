"""Рабочее место мастера: карта, nearby, план, маршрут, RBAC."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.models.enums import Priority
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.models.waybills.waybill_stop import WaybillStop
from app.modules.requests.address_format import normalize_address
from app.modules.requests.repositories import RequestRepository


def _login(client, email: str, password: str = "pass12345"):
    client.post("/auth/logout", follow_redirects=True)
    client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )


def _seed_work(app, *, suffix: str):
    with app.app_context():
        journal_id = RequestRepository.get_default_journal().id
        st_new = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        d_open = db.session.scalar(db.select(DefectStatus).where(DefectStatus.code == "open"))
        category = db.session.scalar(db.select(DefectCategory).where(DefectCategory.code == "lighting"))
        req = Request(
            number=f"26-{suffix}1",
            title="Рядом с дефектом",
            description="Не горит светильник",
            address="ул. Ленина, 27",
            normalized_address=normalize_address("ул. Ленина, 27"),
            street="ул. Ленина",
            district="Ленинский",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_new.id,
            journal_id=journal_id,
            latitude=Decimal("58.6036"),
            longitude=Decimal("49.6681"),
        )
        extra = Request(
            number=f"26-{suffix}2",
            title="Дальше по улице",
            description="Кабель",
            address="ул. Ленина, 31",
            normalized_address=normalize_address("ул. Ленина, 31"),
            street="ул. Ленина",
            district="Ленинский",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_new.id,
            journal_id=journal_id,
            latitude=Decimal("58.6038"),
            longitude=Decimal("49.6684"),
        )
        defect = Defect(
            number=f"DF-26-{suffix}",
            description="Не работает светильник",
            address="ул. Ленина, 25",
            normalized_address=normalize_address("ул. Ленина, 25"),
            street="ул. Ленина",
            district="Ленинский",
            status_id=d_open.id,
            category_id=category.id,
            latitude=Decimal("58.6035"),
            longitude=Decimal("49.6680"),
        )
        db.session.add_all([req, extra, defect])
        db.session.commit()
        return str(req.id), str(extra.id), str(defect.id), req.status_id, defect.status_id


def test_work_orders_access(client):
    page = client.get("/work-orders/", follow_redirects=False)
    assert page.status_code in (302, 401)
    _login(client, "master@test.local")
    page = client.get("/work-orders/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Работа по заявкам" in html
    assert "Мой план работ" in html
    assert "Доступные работы" in html
    assert 'id="opsMap"' in html
    _login(client, "executor@test.local")
    assert client.get("/work-orders/").status_code == 200
    denied = client.post("/work-orders/plan/add", json={"entity_type": "defect", "entity_id": "00000000-0000-0000-0000-000000000001"})
    assert denied.status_code == 403


def test_work_orders_map_colors_and_types(admin_client, app):
    request_id, extra_id, defect_id, _, _ = _seed_work(app, suffix="81")
    payload = admin_client.get("/work-orders/map.json").get_json()
    points = payload["points"]
    by_id = {p["id"]: p for p in points}
    assert by_id[request_id]["type"] == "request"
    assert by_id[request_id]["color"] == "blue"
    assert by_id[defect_id]["type"] == "defect"
    assert by_id[defect_id]["color"] == "red"
    only_defects = admin_client.get("/work-orders/map.json?kind=defect").get_json()["points"]
    assert all(p["type"] == "defect" for p in only_defects)
    assert defect_id in {p["id"] for p in only_defects}
    assert request_id not in {p["id"] for p in only_defects}


def test_work_orders_plan_nearby_reorder_route(client, app):
    _login(client, "master@test.local")
    request_id, extra_id, defect_id, req_status, def_status = _seed_work(app, suffix="82")
    first = client.post(
        "/work-orders/plan/add",
        json={"entity_type": "defect", "entity_id": defect_id},
    )
    assert first.status_code == 200, first.get_data(as_text=True)
    body = first.get_json()
    assert body["ok"] is True
    assert len(body["plan"]["stops"]) == 1
    nearby_ids = {(h["entity_type"], h["entity_id"]) for h in body["nearby"]["hits"]}
    assert ("request", request_id) in nearby_ids
    assert ("request", extra_id) in nearby_ids
    second = client.post(
        "/work-orders/plan/add",
        json={"entity_type": "request", "entity_id": request_id},
    )
    assert second.status_code == 200
    plan = second.get_json()["plan"]
    assert len(plan["stops"]) == 2
    types = {s["entity_type"] for s in plan["stops"]}
    assert types == {"request", "defect"}
    dup = client.post(
        "/work-orders/plan/add",
        json={"entity_type": "defect", "entity_id": defect_id},
    )
    assert dup.status_code == 400
    stop_ids = [s["id"] for s in plan["stops"]]
    reversed_ids = list(reversed(stop_ids))
    reorder = client.post("/work-orders/plan/reorder", json={"stop_ids": reversed_ids})
    assert reorder.status_code == 200
    ordered = [s["id"] for s in reorder.get_json()["plan"]["stops"]]
    assert ordered == reversed_ids
    saved = client.post("/work-orders/plan/save", json={})
    assert saved.status_code == 200
    assert saved.get_json()["plan"]["number"]
    route = client.get("/work-orders/route.json").get_json()
    assert len(route["points"]) == 2
    assert [p["order"] for p in route["points"]] == [1, 2]
    items = client.get("/work-orders/items.json").get_json()["items"]
    by_type = {row["type"] for row in items}
    assert "request" in by_type
    assert "defect" in by_type
    only_def = client.get("/work-orders/items.json?kind=defect").get_json()["items"]
    assert all(row["type"] == "defect" for row in only_def)
    only_req = client.get("/work-orders/items.json?kind=request").get_json()["items"]
    assert all(row["type"] == "request" for row in only_req)
    with app.app_context():
        req = db.session.get(Request, request_id)
        defect = db.session.get(Defect, defect_id)
        assert req.status_id == req_status
        assert defect.status_id == def_status
        mapper_names = {mapper.class_.__name__ for mapper in db.Model.registry.mappers}
        assert "RequestDefect" not in mapper_names
        stops = list(db.session.scalars(db.select(WaybillStop).where(WaybillStop.active_filter())))
        assert any(s.request_id is not None for s in stops)
        assert any(s.defect_id is not None for s in stops)
    completed = client.post("/work-orders/plan/complete", json={})
    assert completed.status_code == 200, completed.get_data(as_text=True)
    with app.app_context():
        req = db.session.get(Request, request_id)
        defect = db.session.get(Defect, defect_id)
        assert req.status_id == req_status
        assert db.session.get(DefectStatus, defect.status_id).code == "fixed"


def test_dispatcher_cannot_edit_work_plan(client, app):
    _login(client, "dispatcher@test.local")
    assert client.get("/work-orders/").status_code == 200
    _, _, defect_id, _, _ = _seed_work(app, suffix="83")
    added = client.post(
        "/work-orders/plan/add",
        json={"entity_type": "defect", "entity_id": defect_id},
    )
    assert added.status_code == 403
    assert client.post("/work-orders/plan/complete", json={}).status_code == 403
