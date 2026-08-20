"""Сквозные HTTP-сценарии: сохранения, файлы, мессенджер, списки /table."""

from __future__ import annotations

import io
import uuid

from app.extensions import db
from app.models.auth.constants import ROLE_EXECUTOR
from app.models.auth.role import Role
from app.models.auth.user import User
from app.models.enums import ProjectStatus, TenderApplicationStatus, WorkObjectKind, WorkObjectStatus

AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _login(client, email: str, password: str = "pass12345"):
    if email == "admin@opora.ru":
        password = "admin123"
    client.get("/auth/logout", follow_redirects=True)
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def _table_html(client, path: str) -> str:
    resp = client.get(f"{path}/table")
    assert resp.status_code == 200, f"{path}/table {resp.get_data(as_text=True)[:1500]}"
    payload = resp.get_json()
    assert payload and "table_html" in payload
    return payload["table_html"]


def _create_object(admin_client) -> tuple[str, str]:
    marker = f"ул. Сквозная {uuid.uuid4().hex[:6]}"
    resp = admin_client.post(
        "/objects/new",
        data={
            "address": marker,
            "object_kind": WorkObjectKind.PLANNED.value,
            "status": WorkObjectStatus.FREE.value,
            "work_type": "Устройство наружного освещения",
            "plan_year": "2026",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {302, 303}, resp.get_data(as_text=True)[:2000]
    object_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    return object_id, marker


def test_saved_rows_appear_in_ajax_tables(admin_client, app):
    request_number = f"SK-{uuid.uuid4().hex[:8].upper()}"
    created_request = admin_client.post(
        "/requests/new",
        data={
            "number": request_number,
            "address": "ул. Проверочная, 1",
            "pp": "ТП-99",
            "received_at": "2026-08-20T12:00",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert created_request.status_code == 302, created_request.get_data(as_text=True)[:2000]
    request_id = created_request.headers["Location"].rstrip("/").split("/")[-1]
    assert request_number in _table_html(admin_client, "/requests")

    object_id, object_marker = _create_object(admin_client)
    assert object_marker in _table_html(admin_client, "/objects")

    with app.app_context():
        admin_id = str(db.session.scalar(db.select(User.id).where(User.email == "admin@opora.ru")))
        executor_role = str(
            db.session.scalar(db.select(Role.id).where(Role.code == ROLE_EXECUTOR))
        )

    project_name = f"Проект сквозной {uuid.uuid4().hex[:6]}"
    created_project = admin_client.post(
        "/projects/new",
        data={
            "code": f"PRJ-SK-{uuid.uuid4().hex[:5].upper()}",
            "name": project_name,
            "object_id": object_id,
            "description": "проверка сохранения",
            "status": ProjectStatus.ACTIVE.value,
            "progress_percent": "10",
            "responsible_id": admin_id,
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert created_project.status_code == 200, created_project.get_data(as_text=True)[:2000]
    project_payload = created_project.get_json()
    assert project_payload["success"] is True
    project_id = project_payload["id"]
    assert project_name in _table_html(admin_client, "/projects")

    modal = admin_client.get(f"/projects/{project_id}", headers=AJAX)
    assert modal.status_code == 200, modal.get_data(as_text=True)[:2000]
    assert project_name in modal.get_data(as_text=True)

    upload = admin_client.post(
        f"/projects/{project_id}/attachment",
        data={"files": [(io.BytesIO(b"project file"), "smeta.txt")], "submit": "Загрузить"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert upload.status_code in {302, 303}, upload.get_data(as_text=True)[:2000]
    project_page = admin_client.get(f"/projects/{project_id}")
    assert project_page.status_code == 200, project_page.get_data(as_text=True)[:1500]
    assert "smeta.txt" in project_page.get_data(as_text=True)
    assert "/attachment/" in project_page.get_data(as_text=True)

    tender_number = f"ТРГ-SK-{uuid.uuid4().hex[:6].upper()}"
    tender_title = f"Торги сквозные {uuid.uuid4().hex[:6]}"
    created_tender = admin_client.post(
        "/tenders/new",
        data={
            "number": tender_number,
            "title": tender_title,
            "status": TenderApplicationStatus.DRAFT.value,
            "object_id": object_id,
            "responsible_id": admin_id,
            "project_ids": [project_id],
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert created_tender.status_code == 200, created_tender.get_data(as_text=True)[:2000]
    assert created_tender.get_json()["success"] is True
    tenders_html = _table_html(admin_client, "/tenders")
    assert tender_number in tenders_html

    contract_number = f"CTR-SK-{uuid.uuid4().hex[:6].upper()}"
    created_contract = admin_client.post(
        "/contracts/new",
        data={
            "contract_type": "work",
            "number": contract_number,
            "title": "Контракт сквозной",
            "description": "описание",
            "contractor_name": "ООО Сквозной",
            "amount": "1500.00",
            "status": "draft",
            "contract_date": "2026-08-20",
            "end_date": "2026-12-31",
            "responsible_id": admin_id,
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert created_contract.status_code == 200, created_contract.get_data(as_text=True)[:2000]
    assert created_contract.get_json()["success"] is True
    assert contract_number in _table_html(admin_client, "/contracts")

    employee_email = f"flow.{uuid.uuid4().hex[:6]}@test.local"
    created_employee = admin_client.post(
        "/employees/new",
        data={
            "email": employee_email,
            "full_name": "Сквозной Сотрудник",
            "password": "pass12345",
            "role_ids": [executor_role],
            "department": "Проверка",
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert created_employee.status_code == 200, created_employee.get_data(as_text=True)[:2000]
    assert created_employee.get_json()["success"] is True
    assert "Сквозной Сотрудник" in _table_html(admin_client, "/employees")

    audit = admin_client.get("/audit/table")
    assert audit.status_code == 200
    audit_html = audit.get_json()["table_html"]
    assert "table-opora" in audit_html

    detail = admin_client.get(f"/requests/{request_id}")
    assert detail.status_code == 200
    assert request_number in detail.get_data(as_text=True)


def test_messenger_send_text_file_and_unread(admin_client, app):
    with app.app_context():
        peer_id = str(db.session.scalar(db.select(User.id).where(User.email == "dispatcher@test.local")))

    opened = admin_client.post(f"/messenger/api/conversations/open/{peer_id}")
    assert opened.status_code == 200, opened.get_data(as_text=True)[:2000]
    conversation_id = opened.get_json()["id"]
    assert conversation_id

    sent = admin_client.post(
        f"/messenger/api/conversations/{conversation_id}/messages",
        json={"body": "Привет из проверки"},
    )
    assert sent.status_code == 201, sent.get_data(as_text=True)[:2000]
    message = sent.get_json()["message"]
    assert message["body"] == "Привет из проверки"
    assert message["is_mine"] is True

    attached = admin_client.post(
        f"/messenger/api/conversations/{conversation_id}/attachments",
        data={"file": (io.BytesIO(b"hello chat"), "chat-note.txt")},
        content_type="multipart/form-data",
    )
    assert attached.status_code == 201, attached.get_data(as_text=True)[:2000]
    file_message = attached.get_json()["message"]
    assert file_message["has_attachment"] is True
    assert file_message["file"]["name"] == "chat-note.txt"
    file_url = file_message["file"]["url"]

    downloaded = admin_client.get(file_url)
    assert downloaded.status_code == 200
    assert downloaded.data == b"hello chat"

    listed = admin_client.get(f"/messenger/api/conversations/{conversation_id}/messages")
    assert listed.status_code == 200
    rows = listed.get_json()["messages"]
    bodies = [row.get("body") for row in rows]
    assert bodies.count("Привет из проверки") == 1
    assert len({row["id"] for row in rows}) == len(rows)
    assert any(row.get("has_attachment") for row in rows)

    replied = admin_client.post(
        f"/messenger/api/conversations/{conversation_id}/messages",
        json={"body": "Ответ на проверку", "reply_to_id": message["id"]},
    )
    assert replied.status_code == 201, replied.get_data(as_text=True)[:2000]
    with_reply = admin_client.get(f"/messenger/api/conversations/{conversation_id}/messages")
    reply_rows = with_reply.get_json()["messages"]
    assert len({row["id"] for row in reply_rows}) == len(reply_rows)
    assert any(row.get("reply_to_id") == message["id"] for row in reply_rows)

    found = admin_client.get("/messenger/api/search?q=проверки")
    assert found.status_code == 200
    assert found.get_json()["results"]

    unread = admin_client.get("/messenger/api/unread-count")
    assert unread.status_code == 200

    _login(admin_client, "dispatcher@test.local")
    peer_unread = admin_client.get("/messenger/api/unread-count")
    assert peer_unread.status_code == 200
    assert peer_unread.get_json()["total"] >= 1

    peer_messages = admin_client.get(f"/messenger/api/conversations/{conversation_id}/messages")
    assert peer_messages.status_code == 200
    assert "Привет из проверки" in [
        row.get("body") for row in peer_messages.get_json()["messages"]
    ]
    peer_file = admin_client.get(file_url)
    assert peer_file.status_code == 200
    assert peer_file.data == b"hello chat"

    after_read = admin_client.get("/messenger/api/unread-count")
    assert after_read.get_json()["total"] == 0


def test_reports_eis_search_and_roles_still_open(admin_client):
    for path in (
        "/",
        "/reports/",
        "/reports/requests",
        "/reports/objects",
        "/eis/",
        "/roles/",
        "/messenger/",
        "/search/api?q=admin",
        "/audit/",
    ):
        resp = admin_client.get(path)
        assert resp.status_code == 200, path

    agreements = admin_client.get("/agreements/")
    html = agreements.get_data(as_text=True)
    assert "vendor/leaflet/leaflet.js" in html
    assert "unpkg.com" not in html
    assert admin_client.get("/agreements/map.json").status_code == 200
    assert admin_client.get("/static/vendor/leaflet/images/marker-icon.png").status_code == 200
