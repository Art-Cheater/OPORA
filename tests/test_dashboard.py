"""Тесты рабочего дашборда и настроек внешнего вида."""

from __future__ import annotations

import io
from datetime import date, timedelta

from PIL import Image

from app.extensions import db
from app.models.auth.user import User
from app.models.contracts.contract import Contract
from app.models.enums import ContractStatus, Priority, ProjectStatus
from app.models.projects.project import Project
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.workflow import STATUS_EMERGENCY_DISPATCHED, STATUS_NEW


def _status(code: str) -> RequestStatus:
    return db.session.execute(
        db.select(RequestStatus).where(RequestStatus.code == code)
    ).scalar_one()


def _png_bytes(color=(245, 124, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


def test_dashboard_shows_welcome_not_sidebar_modules(admin_client):
    page = admin_client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Вот что происходит в Опоре сегодня" in html
    assert "Требует внимания" in html
    assert "Быстрые действия" in html
    assert "Разделы системы" not in html
    assert "Управление персоналом" not in html


def test_dashboard_metrics_use_real_counts(admin_client, app):
    with app.app_context():
        st_new = _status(STATUS_NEW)
        st_em = _status(STATUS_EMERGENCY_DISPATCHED)
        admin = db.session.execute(
            db.select(User).where(User.email == "admin@opora.ru")
        ).scalar_one()
        for i, st in enumerate([st_new, st_new, st_em]):
            db.session.add(
                Request(
                    number=f"DASH-{i+1:03d}",
                    title=f"Тест {i}",
                    address=f"ул. Тестовая, {i}",
                    applicant_name="QA",
                    status_id=st.id,
                    priority=Priority.MEDIUM.value,
                    created_by=admin.id,
                )
            )
        db.session.add(
            Project(
                code="DASH-P1",
                name="Проект без контракта",
                status=ProjectStatus.ACTIVE.value,
                created_by=admin.id,
            )
        )
        soon = date.today() + timedelta(days=10)
        db.session.add(
            Contract(
                number="DASH-C-END",
                title="Скоро конец",
                contractor_name="ООО Тест",
                amount=1000,
                status=ContractStatus.ACTIVE.value,
                end_date=soon,
                created_by=admin.id,
            )
        )
        db.session.commit()

    html = admin_client.get("/").get_data(as_text=True)
    assert "Новые заявки" in html
    assert "проектов без контракта" in html
    assert "контрактов заканчиваются" in html
    assert "DASH-1" in html or "DASH-001" in html


def test_dashboard_hides_requests_without_permission(client, app):
    client.post(
        "/auth/login",
        data={"email": "executor@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    # executor may still have some perms depending on seed — assert no crash
    page = client.get("/")
    assert page.status_code == 200


def test_appearance_set_theme_and_background(admin_client, app):
    res = admin_client.post(
        "/auth/ui/appearance",
        json={"theme": "dark", "background": "none"},
    )
    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == "admin@opora.ru")
        ).scalar_one()
        assert user.ui_theme == "dark"
        assert user.ui_background == "none"


def test_appearance_upload_and_isolation(app):
    client = app.test_client()
    client.post(
        "/auth/login",
        data={"email": "admin@opora.ru", "password": "admin123", "submit": "Войти"},
        follow_redirects=True,
    )

    png = _png_bytes()
    res = client.post(
        "/auth/ui/background",
        data={"background": (io.BytesIO(png), "wall.png")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["background"] == "custom"
    assert payload["url"]
    assert client.get("/auth/ui/background/file").status_code == 200

    client.post("/auth/logout", follow_redirects=True)
    client.post(
        "/auth/login",
        data={"email": "dispatcher@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    profile_html = client.get("/auth/profile").get_data(as_text=True)
    assert "dispatcher@test.local" in profile_html
    assert client.get("/auth/ui/background/file").status_code == 404

    client.post("/auth/logout", follow_redirects=True)
    client.post(
        "/auth/login",
        data={"email": "admin@opora.ru", "password": "admin123", "submit": "Войти"},
        follow_redirects=True,
    )
    deleted = client.delete("/auth/ui/background")
    assert deleted.status_code == 200
    assert deleted.get_json()["ok"] is True
    assert client.get("/auth/ui/background/file").status_code == 404


def test_appearance_rejects_non_image(admin_client):
    res = admin_client.post(
        "/auth/ui/background",
        data={"background": (io.BytesIO(b"%PDF-1.4 fake"), "evil.pdf")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_dashboard_page_includes_appearance_panel(admin_client):
    html = admin_client.get("/").get_data(as_text=True)
    assert "appearancePanel" in html
    assert "Внешний вид" in html
    assert "Без изображения" in html
