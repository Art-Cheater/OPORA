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
        "/audit/",
        "/search/api?q=test",
        "/messenger/",
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

    assert admin_client.post(
        f"/requests/{request_id}/emergency-departed", follow_redirects=False
    ).status_code in (200, 302)

    from app.extensions import db
    from app.models.auth.user import User

    with app.app_context():
        mid = str(
            db.session.scalar(db.select(User.id).where(User.email == "master@test.local"))
        )

    assert admin_client.post(
        f"/requests/{request_id}/assign-master",
        data={"master_id": mid, "submit": "x"},
        follow_redirects=False,
    ).status_code in (200, 302)

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

    assert admin_client.post(
        f"/requests/{request_id}/complete", follow_redirects=False
    ).status_code in (200, 302)


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
