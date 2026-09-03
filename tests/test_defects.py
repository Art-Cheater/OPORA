"""CRUD дефектов, статусы, RBAC и аудит."""

from __future__ import annotations

from app.extensions import db
from app.models.audit.audit_log import AuditLog
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.models.enums import EntityType
from app.modules.defects.workflow import STATUS_IN_PROGRESS, STATUS_OPEN


def _login(client, email: str, password: str = "pass12345"):
    client.post("/auth/logout", follow_redirects=True)
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password, "submit": "Войти"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def _category_id(app) -> str:
    with app.app_context():
        return str(db.session.scalar(db.select(DefectCategory.id).where(DefectCategory.code == "lighting")))


def test_defect_crud_without_request(admin_client, app):
    category_id = _category_id(app)
    created = admin_client.post(
        "/defects/new",
        data={
            "number": "DF-26-1",
            "description": "Не горит светильник",
            "category_id": category_id,
            "address": "ул. Ленина, 10",
            "district": "Ленинский",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302, created.get_data(as_text=True)[:1500]
    defect_id = created.headers["Location"].rstrip("/").split("/")[-1]
    detail = admin_client.get(f"/defects/{defect_id}")
    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "DF-26-1" in html
    assert "Не горит светильник" in html
    with app.app_context():
        item = db.session.get(Defect, defect_id)
        assert item is not None
        status = db.session.get(DefectStatus, item.status_id)
        assert status is not None and status.code == STATUS_OPEN
        audit = db.session.scalar(
            db.select(AuditLog).where(
                AuditLog.entity_type == EntityType.DEFECT.value,
                AuditLog.entity_id == item.id,
            )
        )
        assert audit is not None


def test_defect_status_change(admin_client, app):
    category_id = _category_id(app)
    created = admin_client.post(
        "/defects/new",
        data={
            "number": "DF-26-2",
            "description": "Опора наклонена",
            "category_id": category_id,
            "address": "ул. Попова, 5",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    defect_id = created.headers["Location"].rstrip("/").split("/")[-1]
    changed = admin_client.post(
        f"/defects/{defect_id}/status",
        data={"status_code": STATUS_IN_PROGRESS, "comment": "Взяли в работу", "submit": "x"},
        follow_redirects=False,
    )
    assert changed.status_code in (200, 302)
    with app.app_context():
        item = db.session.get(Defect, defect_id)
        status = db.session.get(DefectStatus, item.status_id)
        assert status.code == STATUS_IN_PROGRESS


def test_defect_list_status_action_and_permission(admin_client, client, app):
    category_id = _category_id(app)
    created = admin_client.post(
        "/defects/new",
        data={
            "number": "DF-26-3",
            "description": "Кабель повреждён",
            "category_id": category_id,
            "address": "ул. Мира, 3",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    defect_id = created.headers["Location"].rstrip("/").split("/")[-1]
    table = admin_client.get("/defects/table").get_json()["table_html"]
    assert 'data-opora-action="status"' in table
    assert "В работе" in table
    assert "Выполнен" in table
    ajax = admin_client.post(
        f"/defects/{defect_id}/status",
        json={"status_code": STATUS_IN_PROGRESS, "comment": "Смена из списка"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert ajax.status_code == 200
    assert ajax.get_json()["ok"] is True
    with app.app_context():
        item = db.session.get(Defect, defect_id)
        status = db.session.get(DefectStatus, item.status_id)
        assert status.code == STATUS_IN_PROGRESS
        audit = db.session.scalar(
            db.select(AuditLog).where(
                AuditLog.entity_type == EntityType.DEFECT.value,
                AuditLog.entity_id == item.id,
                AuditLog.action == "status_change",
            )
        )
        assert audit is not None
    _login(client, "executor@test.local")
    denied = client.post(
        f"/defects/{defect_id}/status",
        json={"status_code": "fixed"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert denied.status_code == 403


def test_defect_files_and_list_shell(admin_client, app):
    page = admin_client.get("/defects/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "opora-loading" in html
    table = admin_client.get("/defects/table")
    assert table.status_code == 200
    payload = table.get_json()
    assert "table_html" in payload
    map_resp = admin_client.get("/defects/map.json")
    assert map_resp.status_code == 200
    assert "points" in map_resp.get_json()


def test_executor_cannot_create_defect(client):
    _login(client, "executor@test.local")
    page = client.get("/defects/")
    assert page.status_code == 200
    created = client.post(
        "/defects/new",
        data={"number": "DF-26-9", "description": "x", "address": "a", "submit": "Сохранить"},
        follow_redirects=False,
    )
    assert created.status_code in (302, 403)
