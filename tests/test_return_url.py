"""Безопасный return_url на карточках заявок и дефектов."""

from __future__ import annotations

from urllib.parse import quote

from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.models.enums import Priority
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.repositories import RequestRepository


def _make_request(app):
    with app.app_context():
        journal = RequestRepository.get_default_journal()
        status = db.session.scalar(db.select(RequestStatus).where(RequestStatus.code == "new"))
        item = Request(
            number="26-8401",
            title="Назад",
            address="Тестовая, 1",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=status.id,
            journal_id=journal.id,
        )
        db.session.add(item)
        db.session.commit()
        return str(item.id), str(journal.id)


def _make_defect(app):
    with app.app_context():
        status = db.session.scalar(db.select(DefectStatus).where(DefectStatus.code == "open"))
        category = db.session.scalar(db.select(DefectCategory).where(DefectCategory.code == "other"))
        item = Defect(
            number="DF-26-84",
            description="Назад",
            address="Тестовая, 2",
            status_id=status.id,
            category_id=category.id,
        )
        db.session.add(item)
        db.session.commit()
        return str(item.id)


def test_request_back_keeps_filters(admin_client, app):
    request_id, journal_id = _make_request(app)
    return_to = f"/requests/?journal_id={journal_id}&status=new"
    page = admin_client.get(f"/requests/{request_id}?return_url={quote(return_to)}")
    assert page.status_code == 200
    html = page.get_data(as_text=True).replace("&amp;", "&")
    assert "Назад к заявкам" in html
    assert f"journal_id={journal_id}" in html
    assert "status=new" in html
    assert "Связанные дефекты" not in html
    assert "Связать" not in html


def test_request_back_from_work_orders(admin_client, app):
    request_id, _ = _make_request(app)
    page = admin_client.get(
        f"/requests/{request_id}",
        headers={"Referer": "http://localhost/work-orders/"},
    )
    html = page.get_data(as_text=True)
    assert "Назад к работе по заявкам" in html
    assert 'href="/work-orders/"' in html


def test_return_url_rejects_open_redirect(admin_client, app):
    request_id, _ = _make_request(app)
    page = admin_client.get(f"/requests/{request_id}?return_url={quote('https://evil.example/phish')}")
    html = page.get_data(as_text=True)
    assert "https://evil.example/phish" not in html
    assert "Назад к заявкам" in html
    slash = admin_client.get(f"/requests/{request_id}?return_url={quote('//evil.example')}")
    assert "//evil.example" not in slash.get_data(as_text=True)


def test_defect_back_and_no_link_ui(admin_client, app):
    defect_id = _make_defect(app)
    page = admin_client.get(f"/defects/{defect_id}?return_url={quote('/defects/')}")
    html = page.get_data(as_text=True)
    assert "Назад к заявкам" in html
    assert "Связанные заявки" not in html
    assert admin_client.post(f"/defects/{defect_id}/link-request", data={"request_id": "x"}).status_code == 404
    from_tab = admin_client.get(f"/defects/{defect_id}?return_url={quote('/requests/?tab=defects')}")
    tab_html = from_tab.get_data(as_text=True).replace("&amp;", "&")
    assert "Назад к заявкам" in tab_html
    assert "tab=defects" in tab_html
