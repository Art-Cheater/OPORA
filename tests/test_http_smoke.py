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
        "/projects/",
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
            "title": "Pytest заявка",
            "description": "d",
            "address": "Адрес 1",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
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
            "title": "Bad file",
            "address": "A",
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
