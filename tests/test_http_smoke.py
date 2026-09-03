"""HTTP smoke + RBAC тесты."""

from __future__ import annotations

import io
import uuid


def test_login_required_redirect(client):
    resp = client.get("/requests/", follow_redirects=False)
    assert resp.status_code in (302, 401)


def test_admin_pages(admin_client):
    for path in (
        "/",
        "/requests/",
        "/objects/",
        "/projects/",
        "/tenders/",
        "/contracts/",
        "/reports/requests",
        "/reports/",
        "/reports/objects",
        "/audit/",
        "/search/api?q=test",
        "/messenger/",
        "/defects/",
        "/waybills/",
        "/work-orders/",
    ):
        resp = admin_client.get(path)
        assert resp.status_code == 200, path


def test_executor_denied_reports(client):
    client.post(
        "/auth/login",
        data={"email": "executor@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    resp = client.get("/reports/requests", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_request_lifecycle_and_upload(admin_client, app):
    number = f"T-{uuid.uuid4().hex[:8].upper()}"
    resp = admin_client.post(
        "/requests/new",
        data={
            "number": number,
            "address": "Адрес 1",
            "pp": "ТП-12",
            "received_at": "2026-08-10T12:00",
            "dispatcher_name": "Иванова А.С.",
            "description": "d",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.get_data(as_text=True)[:500]
    location = resp.headers["Location"]
    request_id = location.rstrip("/").split("/")[-1]

    upload = admin_client.post(
        f"/requests/{request_id}/attachment",
        data={
            "files": [(io.BytesIO(b"hello pytest"), "note.txt")],
            "submit": "Загрузить",
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert upload.status_code in (200, 302)

    detail = admin_client.get(f"/requests/{request_id}")
    html = detail.get_data(as_text=True)
    assert "Выполнено" in html
    assert "Передать мастеру" not in html
    assert "Выехала аварийная бригада" not in html
    assert "Принята мастером" not in html

    assert admin_client.post(
        f"/requests/{request_id}/complete", follow_redirects=False
    ).status_code in (200, 302)

    from app.extensions import db
    from app.models.requests.request import Request
    from app.models.requests.request_status import RequestStatus

    with app.app_context():
        item = db.session.get(Request, request_id)
        status = db.session.get(RequestStatus, item.status_id)
        assert status.code == "completed"


def test_edit_completed_request_status_back_to_new(admin_client, app):
    number = f"S-{uuid.uuid4().hex[:8].upper()}"
    created = admin_client.post(
        "/requests/new",
        data={
            "number": number,
            "address": "Адрес статуса",
            "pp": "ПП 69",
            "received_at": "2026-08-10T12:00",
            "dispatcher_name": "Иванова А.С.",
            "description": "Проверка статуса",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302, created.get_data(as_text=True)[:500]
    request_id = created.headers["Location"].rstrip("/").split("/")[-1]
    assert admin_client.post(
        f"/requests/{request_id}/complete", follow_redirects=False
    ).status_code in (200, 302)

    from app.extensions import db
    from app.models.requests.request import Request
    from app.models.requests.request_status import RequestStatus

    with app.app_context():
        item = db.session.get(Request, request_id)
        assert db.session.get(RequestStatus, item.status_id).code == "completed"
        journal_id = str(item.journal_id)
        new_id = str(db.session.scalar(db.select(RequestStatus.id).where(RequestStatus.code == "new")))
        in_progress_id = str(
            db.session.scalar(db.select(RequestStatus.id).where(RequestStatus.code == "in_progress"))
        )

    edit_page = admin_client.get(f"/requests/{request_id}/edit")
    assert edit_page.status_code == 200, edit_page.get_data(as_text=True)[:2000]
    edit_html = edit_page.get_data(as_text=True)
    assert 'name="status_id"' in edit_html
    assert "Новая" in edit_html
    assert "В работе" in edit_html
    assert "Выполнено" in edit_html
    assert "Сохранить изменения" in edit_html

    saved = admin_client.post(
        f"/requests/{request_id}/edit",
        data={
            "number": number,
            "address": "Адрес статуса",
            "pp": "ПП 69",
            "received_at": "2026-08-10T12:00",
            "dispatcher_name": "Иванова А.С.",
            "description": "Проверка статуса",
            "applicant_name": "Тест",
            "priority": "medium",
            "journal_id": journal_id,
            "status_id": new_id,
            "submit": "Сохранить изменения",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 302, saved.get_data(as_text=True)[:2000]
    detail = admin_client.get(f"/requests/{request_id}")
    assert "Новая" in detail.get_data(as_text=True)
    with app.app_context():
        item = db.session.get(Request, request_id)
        assert db.session.get(RequestStatus, item.status_id).code == "new"

    assert admin_client.post(
        f"/requests/{request_id}/complete", follow_redirects=False
    ).status_code in (200, 302)
    back_to_work = admin_client.post(
        f"/requests/{request_id}/edit",
        data={
            "number": number,
            "address": "Адрес статуса",
            "pp": "ПП 69",
            "received_at": "2026-08-10T12:00",
            "dispatcher_name": "Иванова А.С.",
            "description": "Проверка статуса",
            "applicant_name": "Тест",
            "priority": "medium",
            "journal_id": journal_id,
            "status_id": in_progress_id,
            "submit": "Сохранить изменения",
        },
        follow_redirects=False,
    )
    assert back_to_work.status_code == 302, back_to_work.get_data(as_text=True)[:2000]
    work_page = admin_client.get(f"/requests/{request_id}")
    assert "В работе" in work_page.get_data(as_text=True)
    with app.app_context():
        item = db.session.get(Request, request_id)
        assert db.session.get(RequestStatus, item.status_id).code == "in_progress"


def test_old_request_status_still_completes_without_master(admin_client, app):
    from app.extensions import db
    from app.models.enums import Priority
    from app.models.requests.request import Request
    from app.models.requests.request_status import RequestStatus
    from app.modules.requests.repositories import RequestRepository

    with app.app_context():
        st = db.session.scalar(
            db.select(RequestStatus).where(RequestStatus.code == "emergency_dispatched")
        )
        journal = RequestRepository.get_default_journal()
        item = Request(
            number="26-OLD1",
            title="Старая заявка",
            address="Адрес старый",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=st.id,
            journal_id=journal.id,
            responsible_id=None,
        )
        db.session.add(item)
        db.session.commit()
        rid = str(item.id)
    html = admin_client.get(f"/requests/{rid}").get_data(as_text=True)
    assert "Выполнено" in html
    assert "Передать мастеру" not in html
    assert admin_client.post(f"/requests/{rid}/complete", follow_redirects=False).status_code in (200, 302)
    with app.app_context():
        item = db.session.get(Request, uuid.UUID(rid))
        status = db.session.get(RequestStatus, item.status_id)
        assert item.responsible_id is None
        assert status.code == "completed"


def test_reports_export_requires_permission(admin_client):
    resp = admin_client.get("/reports/requests/export?period=week")
    # admin has reports.export via full catalog
    assert resp.status_code == 200
    assert "text/csv" in (resp.mimetype or "")


def test_reject_forbidden_upload_extension(admin_client, app):
    number = f"B-{uuid.uuid4().hex[:8].upper()}"
    resp = admin_client.post(
        "/requests/new",
        data={
            "number": number,
            "address": "A",
            "pp": "ТП-1",
            "received_at": "2026-08-10T12:00",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "T",
            "priority": "low",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    request_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    bad = admin_client.post(
        f"/requests/{request_id}/attachment",
        data={
            "files": [(io.BytesIO(b"MZ exe"), "virus.exe")],
            "submit": "Загрузить",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert bad.status_code == 200
    body = bad.get_data(as_text=True).lower()
    assert "exe" in body or "не разреш" in body or "ошиб" in body or "danger" in body


def _create_request(admin_client) -> str:
    number = f"O-{uuid.uuid4().hex[:8].upper()}"
    resp = admin_client.post(
        "/requests/new",
        data={
            "number": number,
            "address": "Лепсе 79",
            "district": "Ленинский",
            "pp": "ТП-1",
            "received_at": "2026-08-13T10:00",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.get_data(as_text=True)[:2000]
    return resp.headers["Location"].rstrip("/").split("/")[-1]


def test_request_open_list_detail_and_forms(admin_client):
    ajax = {"X-Requested-With": "XMLHttpRequest"}
    request_id = _create_request(admin_client)

    list_resp = admin_client.get("/requests/")
    assert list_resp.status_code == 200, list_resp.get_data(as_text=True)[:2000]
    list_html = list_resp.get_data(as_text=True)
    assert "journal-tabs" in list_html
    assert "Найти" in list_html
    assert 'id="opsMap"' in list_html
    table = admin_client.get("/requests/table")
    assert table.status_code == 200
    payload = table.get_json()
    assert "Лепсе" in payload["table_html"]
    assert "Выполнено" in payload["table_html"]
    assert "Передать мастеру" not in payload["table_html"]
    assert "Выехала аварийная" not in payload["table_html"]
    assert "Показано" in payload["pagination_html"]
    assert "на странице" in payload["pagination_html"]

    page = admin_client.get(f"/requests/{request_id}")
    assert page.status_code == 200, page.get_data(as_text=True)[:2000]
    page_body = page.get_data(as_text=True)
    assert "Лепсе" in page_body
    assert "Район" in page_body or "Ленинский" in page_body

    modal = admin_client.get(f"/requests/{request_id}", headers=ajax)
    assert modal.status_code == 200, modal.get_data(as_text=True)[:2000]
    modal_body = modal.get_data(as_text=True)
    assert "data-opora-detail-form" in modal_body
    assert "Добавить комментарий" in modal_body

    create_modal = admin_client.get("/requests/new", headers=ajax)
    assert create_modal.status_code == 200, create_modal.get_data(as_text=True)[:2000]
    create_body = create_modal.get_data(as_text=True)
    assert 'name="address"' in create_body
    assert "data-address-suggestions" in create_body

    edit_page = admin_client.get(f"/requests/{request_id}/edit")
    assert edit_page.status_code == 200, edit_page.get_data(as_text=True)[:2000]

    comment = admin_client.post(
        f"/requests/{request_id}/comment",
        data={"body": "Проверка комментария", "submit": "Добавить комментарий"},
        headers=ajax,
        follow_redirects=False,
    )
    assert comment.status_code == 200, comment.get_data(as_text=True)[:2000]
    payload = comment.get_json()
    assert payload and payload.get("success") is True

    dup = admin_client.get(
        "/requests/api/open-by-address?address=ул.+Лепсе+д.79",
        headers=ajax,
    )
    assert dup.status_code == 200, dup.get_data(as_text=True)[:1000]
    dup_payload = dup.get_json()
    assert dup_payload["found"] is True
    assert dup_payload["id"] == request_id


def test_employee_and_tender_shared_forms_open(admin_client):
    ajax = {"X-Requested-With": "XMLHttpRequest"}

    employee_page = admin_client.get("/employees/new")
    assert employee_page.status_code == 200, employee_page.get_data(as_text=True)[:2000]
    assert 'name="position_id"' in employee_page.get_data(as_text=True)

    employee_modal = admin_client.get("/employees/new", headers=ajax)
    assert employee_modal.status_code == 200, employee_modal.get_data(as_text=True)[:2000]
    assert 'name="position_id"' in employee_modal.get_data(as_text=True)

    tender_page = admin_client.get("/tenders/new")
    assert tender_page.status_code == 200, tender_page.get_data(as_text=True)[:2000]
    tender_modal = admin_client.get("/tenders/new", headers=ajax)
    assert tender_modal.status_code == 200, tender_modal.get_data(as_text=True)[:2000]
    assert 'name="object_id"' in tender_modal.get_data(as_text=True)
    assert "data-choice-url" in tender_modal.get_data(as_text=True)

    choices = admin_client.get("/objects/api/choices", headers=ajax)
    assert choices.status_code == 200, choices.get_data(as_text=True)[:1000]
    assert isinstance(choices.get_json().get("items"), list)


def test_list_rows_use_status_tones(admin_client):
    _create_request(admin_client)
    requests_page = admin_client.get("/requests/table")
    assert requests_page.status_code == 200
    assert "table-row-lifecycle" in requests_page.get_json()["table_html"]
    assert "table-row-new" in requests_page.get_json()["table_html"]

    employees_page = admin_client.get("/employees/table")
    assert employees_page.status_code == 200
    assert "table-row-lifecycle" in employees_page.get_json()["table_html"]

    for path in ("/projects/", "/contracts/", "/objects/", "/tenders/"):
        response = admin_client.get(path)
        assert response.status_code == 200, path
        html = response.get_data(as_text=True)
        assert "opora-loading" in html, path
        table = admin_client.get(f"{path}table")
        assert table.status_code == 200, path
        assert "table_html" in table.get_json()


def test_static_assets_are_public_cached_and_not_cdn_fallback(client, admin_client):
    for path in (
        "/static/css/main.css",
        "/static/js/main.js",
        "/static/js/opora-list.js",
        "/static/vendor/bootstrap.min.css",
        "/static/vendor/bootstrap.bundle.min.js",
        "/static/vendor/bootstrap-icons.min.css",
        "/static/vendor/fonts/bootstrap-icons.woff2",
        "/static/vendor/leaflet/leaflet.css",
        "/static/vendor/leaflet/leaflet.js",
        "/static/vendor/leaflet/images/marker-icon.png",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        cache = response.headers.get("Cache-Control", "")
        assert "max-age" in cache
        assert "public" in cache

    page = admin_client.get("/requests/")
    html = page.get_data(as_text=True)
    assert "cdn.jsdelivr.net" not in html
    assert "unpkg.com" not in html
    assert "static/css/main.css?v=" in html
    assert "static/vendor/bootstrap.min.css?v=" in html
    assert "static/js/opora-list.js?v=" in html
    list_js = client.get("/static/js/opora-list.js")
    assert list_js.status_code == 200
    assert b"const AJAX_HEADERS" in list_js.data

    first = client.get("/static/css/main.css")
    etag = first.headers.get("ETag")
    assert etag
    cached = client.get("/static/css/main.css", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    cache = cached.headers.get("Cache-Control", "")
    assert "max-age" in cache
    assert "immutable" in cache


def test_logged_in_static_does_not_hit_the_database(admin_client, app):
    from app.core.performance import count_queries
    from app.extensions import db

    with app.app_context():
        with count_queries(db.engine) as counter:
            response = admin_client.get("/static/js/main.js")
        assert response.status_code == 200
        assert counter.count == 0

