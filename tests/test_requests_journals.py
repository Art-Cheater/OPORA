"""Журналы заявок, вкладка дефектов, SPA без полной перезагрузки."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.base import format_local_dt
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.models.enums import Priority
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.address_format import address_expression_anchor, normalize_address
from app.modules.requests.repositories import RequestRepository


def test_requests_journals_include_defects_tab(admin_client):
    page = admin_client.get("/requests/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "journal-tabs" in html
    assert "Все" in html
    assert "Заявки в деревнях Октябрьского района" in html
    assert "Заявки в деревнях Нововятского района" in html
    assert "Заявки в деревнях Ленинского района" in html
    assert "Дефекты" in html
    assert 'id="opsMap"' not in html
    assert "js/ops-map.js" not in html
    assert "vendor/leaflet/leaflet.js" not in html
    assert "css/requests-journal.css" in html
    assert "Поиск" in html
    assert "Сбор" in html
    assert "Новая заявка" in html
    assert 'data-tour="defects"' not in html
    assert ">Путевые листы</span>" not in html


def test_request_create_journal_can_open_defect_creation(admin_client, client):
    page = admin_client.get("/requests/new")
    html = page.get_data(as_text=True)
    assert '<option value="__defects__">Дефекты</option>' in html
    assert 'data-defect-create-url="/defects/new"' in html

    redirected = admin_client.post(
        "/requests/new",
        data={"journal_id": "__defects__"},
        follow_redirects=False,
    )
    assert redirected.status_code == 302
    assert redirected.headers["Location"].endswith("/defects/new")

    ajax = admin_client.post(
        "/requests/new",
        data={"journal_id": "__defects__"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert ajax.status_code == 200
    assert ajax.get_json()["redirect_url"] == "/defects/new"

    client.post("/auth/logout", follow_redirects=True)
    client.post(
        "/auth/login",
        data={"email": "executor@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    executor_html = client.get("/requests/new").get_data(as_text=True)
    assert 'value="__defects__"' not in executor_html


def test_request_create_preserves_multiple_houses_and_moscow_time(admin_client, app):
    response = admin_client.post(
        "/requests/new",
        data={
            "number": "26-9921",
            "address": "Лепсе 12, 15",
            "received_at": "2026-09-04T10:20",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    request_id = response.headers["Location"].rstrip("/").split("/")[-1]
    with app.app_context():
        item = db.session.get(Request, request_id)
        assert item.address == "Лепсе 12, 15"
        assert item.normalized_address == "Киров, улица Лепсе, дом 12"
        assert format_local_dt(item.received_at) == "04.09.2026 10:20"
    assert address_expression_anchor("Лепсе 12-15") == "Лепсе 12"
    assert address_expression_anchor("Лепсе 12/1, 15") is None


def test_requests_hide_completed_filter(admin_client, app):
    with app.app_context():
        journal_id = RequestRepository.get_default_journal().id
        completed = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "completed"))
        item = Request(
            number="26-9922",
            title="Завершённая",
            address="ул. Тест, 22",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=completed.id,
            journal_id=journal_id,
        )
        db.session.add(item)
        db.session.commit()
    visible = admin_client.get("/requests/table?number=26-9922").get_json()["table_html"]
    hidden = admin_client.get("/requests/table?number=26-9922&hide_completed=1").get_json()["table_html"]
    assert "26-9922" in visible
    assert "26-9922" not in hidden


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
    assert 'id="opsMap"' not in html
    assert "js/ops-map.js" not in html
    assert "vendor/leaflet/leaflet.js" not in html
    assert 'id="defectFilterForm"' in html
    assert 'id="defectsTableContainer"' in html
    assert "journal-tabs" in html
    table = admin_client.get("/defects/table")
    payload = table.get_json()
    assert payload["entity"] == "defect"
    assert "Описание" in payload["table_html"]
    assert "Ответственный" in payload["table_html"]
    assert "DF-26-91" in payload["table_html"]
    assert 'id="requestFilterForm"' not in html
    assert "ПП (пункт питания)" not in payload["table_html"]


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


def test_spa_nav_requests_keeps_journals_and_map(admin_client):
    page = admin_client.get("/requests/", headers={"X-Opora-Nav": "1"})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="appContent"' in html
    assert 'id="opsMap"' not in html
    assert "journal-tabs" in html
    assert "Дефекты" in html
    assert "js/ops-map.js" not in html
    assert "vendor/leaflet/leaflet.js" not in html
    assert "css/requests-journal.css" in html
    assert 'id="appShell"' not in html
    assert page.headers.get("X-Opora-Partial") == "1"


def test_defects_journal_never_returns_requests(admin_client, app):
    with app.app_context():
        journal_id = RequestRepository.get_default_journal().id
        st_new = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        d_open = db.session.scalar(db.select(DefectStatus).where(DefectStatus.code == "open"))
        category = db.session.scalar(db.select(DefectCategory).where(DefectCategory.code == "lighting"))
        req = Request(
            number="25-9501",
            title="Заявка не должна попасть в дефекты",
            address="ул. Ленина, 1",
            normalized_address=normalize_address("ул. Ленина, 1"),
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st_new.id,
            journal_id=journal_id,
        )
        defect = Defect(
            number="DF-26-9501",
            description="Не горит светильник на опоре",
            address="ул. Мира, 10",
            status_id=d_open.id,
            category_id=category.id,
        )
        db.session.add_all([req, defect])
        db.session.commit()

    page = admin_client.get("/requests/?tab=defects")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="defectFilterForm"' in html
    assert 'id="defectsTableContainer"' in html
    assert 'data-base-url="/defects"' in html
    assert 'data-list-kind="defects"' in html
    assert 'id="requestFilterForm"' not in html
    assert 'id="requestsTableContainer"' not in html
    assert 'data-opora-journal="defects"' in html

    spa = admin_client.get("/requests/?tab=defects", headers={"X-Opora-Nav": "1"})
    spa_html = spa.get_data(as_text=True)
    assert 'data-base-url="/defects"' in spa_html
    assert 'id="defectFilterForm"' in spa_html
    assert 'id="requestFilterForm"' not in spa_html

    defects_table = admin_client.get("/defects/table").get_json()
    assert defects_table["entity"] == "defect"
    assert "DF-26-9501" in defects_table["table_html"]
    assert "25-9501" not in defects_table["table_html"]
    assert "Не горит светильник на опоре" in defects_table["table_html"]
    assert "ул. Мира, 10" in defects_table["table_html"]
    assert "ПП (пункт питания)" not in defects_table["table_html"]
    assert "Диспетчер" not in defects_table["table_html"]

    via_requests = admin_client.get("/requests/table?tab=defects").get_json()
    assert via_requests["entity"] == "defect"
    assert "DF-26-9501" in via_requests["table_html"]
    assert "25-9501" not in via_requests["table_html"]
    assert "Описание" in via_requests["table_html"]

    requests_table = admin_client.get("/requests/table").get_json()
    assert requests_table["entity"] == "request"
    assert "25-9501" in requests_table["table_html"]
    assert "DF-26-9501" not in requests_table["table_html"]


def test_spa_nav_work_orders_keeps_available_list(admin_client):
    page = admin_client.get("/work-orders/", headers={"X-Opora-Nav": "1"})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="appContent"' in html
    assert 'id="opsMap"' in html
    assert "Работа по заявкам" in html or "Работа с заявками" in html
    assert "Доступные работы" in html
    assert 'id="workOrderRoot"' in html
    assert "js/work-orders.js" in html
    assert "Мой план работ" in html
    assert "workbench__top" in html
    assert 'id="appShell"' not in html
    assert page.headers.get("X-Opora-Partial") == "1"


def test_spa_list_scripts_bind_navigation_without_reload():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    ops = (root / "app/static/js/ops-map.js").read_text(encoding="utf-8")
    main = (root / "app/static/js/main.js").read_text(encoding="utf-8")
    work = (root / "app/static/js/work-orders.js").read_text(encoding="utf-8")
    opora_list = (root / "app/static/js/opora-list.js").read_text(encoding="utf-8")
    plan_new = (root / "app/static/js/work-plan-new.js").read_text(encoding="utf-8")
    plan_detail = (root / "app/static/js/work-plan-detail.js").read_text(encoding="utf-8")
    assert "OporaOpsMap" in work
    assert "opora:navigated" in work
    assert 'path === "/requests/" || path === "/defects/"' in main
    assert 'data-opora-journal' in main
    assert 'listKindFromLocation' in opora_list
    assert 'baseUrl: defects ? "/defects"' in opora_list
    assert "reloadListMap" in opora_list
    assert "completeFromList" in opora_list
    assert "changeStatusFromList" in opora_list
    assert "return_url=" in opora_list
    assert "OporaRequestsJournal" in main
    assert "OporaWorkPlanNew" in main
    assert "OporaWorkPlanDetail" in main
    assert "OporaObjectForm" in main
    assert "ResizeObserver" in ops
    assert "destroy()" in ops
    assert "location.reload" not in ops
    assert "location.reload" not in main
    assert "location.reload" not in work
    assert "location.reload" not in plan_new
    assert "location.reload" not in plan_detail
    assert "js-pick" not in plan_new
    assert "setTimeout(bootOps" not in main
    assert "script.async = false" in main


def test_requests_number_sort_and_repeat_plus(admin_client, app):
    with app.app_context():
        journal_id = RequestRepository.get_default_journal().id
        st_new = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        for number, address in (("26-1", "ул. А, 1"), ("26-2", "ул. А, 2"), ("26-10", "ул. А, 10")):
            db.session.add(
                Request(
                    number=number,
                    title=address,
                    description="Сортировка",
                    address=address,
                    applicant_name="QA",
                    priority=Priority.MEDIUM.value,
                    status_id=st_new.id,
                    journal_id=journal_id,
                )
            )
        db.session.commit()
    payload = admin_client.get("/requests/table?sort_by=number&sort_dir=asc").get_json()
    assert payload["entity"] == "request"
    html = payload["table_html"]
    assert "Внутренняя ошибка" not in html
    pos1 = html.find('data-number="26-1"')
    pos2 = html.find('data-number="26-2"')
    pos10 = html.find('data-number="26-10"')
    assert 0 <= pos1 < pos2 < pos10
    assert "data-opora-repeat" in html
    assert "journal-repeat-btn" in html
    page = admin_client.get("/requests/")
    assert "Сбор" in page.get_data(as_text=True)
    assert "overflow-x: auto" not in page.get_data(as_text=True) or "journal-tabs" in page.get_data(as_text=True)

