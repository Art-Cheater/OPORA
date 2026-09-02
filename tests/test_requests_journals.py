"""Журналы заявок, вкладка дефектов, SPA без полной перезагрузки."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.models.enums import Priority
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.address_format import normalize_address
from app.modules.requests.repositories import RequestRepository


def test_requests_journals_include_defects_tab(admin_client):
    page = admin_client.get("/requests/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Журналы:" in html
    assert "Все" in html
    assert "Заявки в деревнях Октябрьского района" in html
    assert "Заявки в деревнях Нововятского района" in html
    assert "Заявки в деревнях Ленинского района" in html
    assert "Дефекты" in html
    assert 'id="opsMap"' in html
    assert 'data-tour="defects"' not in html
    assert ">Путевые листы</span>" not in html


def test_requests_defects_tab_looks_like_journal(admin_client, app):
    with app.app_context():
        status = db.session.scalar(db.select(DefectStatus).where(DefectStatus.code == "open"))
        category = db.session.scalar(db.select(DefectCategory).where(DefectCategory.code == "lighting"))
        item = Defect(
            number="DF-26-91",
            description="Не работает светильник",
            address="ул. Ленина, 25",
            status_id=status.id,
            category_id=category.id,
        )
        db.session.add(item)
        db.session.commit()
    page = admin_client.get("/requests/?tab=defects")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="opsMap"' in html
    assert 'id="defectFilterForm"' in html
    assert 'id="defectsTableContainer"' in html
    assert "Журналы:" in html
    table = admin_client.get("/defects/table")
    payload = table.get_json()
    assert "Описание" in payload["table_html"]
    assert "Ответственный" in payload["table_html"]
    assert "DF-26-91" in payload["table_html"]


def test_requests_all_map_includes_requests_and_defects(admin_client, app):
    with app.app_context():
        journal_id = RequestRepository.get_default_journal().id
        st_new = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        d_open = db.session.scalar(db.select(DefectStatus).where(DefectStatus.code == "open"))
        category = db.session.scalar(db.select(DefectCategory).where(DefectCategory.code == "lighting"))
        req = Request(
            number="26-9101",
            title="Карта",
            address="ул. Ленина, 27",
            normalized_address=normalize_address("ул. Ленина, 27"),
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_new.id,
            journal_id=journal_id,
            latitude=Decimal("58.6036"),
            longitude=Decimal("49.6681"),
        )
        defect = Defect(
            number="DF-26-92",
            description="Опора",
            address="ул. Ленина, 25",
            status_id=d_open.id,
            category_id=category.id,
            latitude=Decimal("58.6035"),
            longitude=Decimal("49.6680"),
        )
        db.session.add_all([req, defect])
        db.session.commit()
        request_id, defect_id, journal = str(req.id), str(defect.id), str(journal_id)
    all_points = {p["id"]: p for p in admin_client.get("/requests/map.json").get_json()["points"]}
    assert all_points[request_id]["type"] == "request"
    assert all_points[defect_id]["type"] == "defect"
    journal_points = admin_client.get(f"/requests/map.json?journal_id={journal}").get_json()["points"]
    assert all(p["type"] == "request" for p in journal_points)
    assert request_id in {p["id"] for p in journal_points}
    assert defect_id not in {p["id"] for p in journal_points}


def test_spa_nav_requests_keeps_map_and_journals(admin_client):
    page = admin_client.get("/requests/", headers={"X-Opora-Nav": "1"})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="appContent"' in html
    assert 'id="opsMap"' in html
    assert "Журналы:" in html
    assert "Дефекты" in html
    assert "js/ops-map.js" in html
    assert 'id="appShell"' not in html
    assert page.headers.get("X-Opora-Partial") == "1"


def test_spa_nav_work_orders_keeps_available_list(admin_client):
    page = admin_client.get("/work-orders/", headers={"X-Opora-Nav": "1"})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="appContent"' in html
    assert 'id="opsMap"' in html
    assert "Доступные работы" in html
    assert "Мой план работ" in html
    assert "js/work-orders.js" in html
    assert "js/ops-map.js" in html
    assert "workbench__top" in html
    assert "workbench__available" in html
    assert 'id="appShell"' not in html
    assert page.headers.get("X-Opora-Partial") == "1"


def test_spa_map_scripts_bind_navigation_without_reload():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ops = (root / "app/static/js/ops-map.js").read_text(encoding="utf-8")
    main = (root / "app/static/js/main.js").read_text(encoding="utf-8")
    work = (root / "app/static/js/work-orders.js").read_text(encoding="utf-8")
    assert "opora:navigated" in ops
    assert "opora:navigated" in work
    assert "ResizeObserver" in ops
    assert "destroy()" in ops
    assert "location.reload" not in ops
    assert "location.reload" not in main
    assert "location.reload" not in work
    assert "setTimeout(bootOps" not in main
    assert "script.async = false" in main
