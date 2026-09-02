"""Ручная связь заявка ↔ дефект удалена: nearby не создаёт M2M."""

from __future__ import annotations

from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.requests.request import Request
from app.modules.requests.repositories import RequestRepository


def test_manual_request_defect_link_removed(admin_client, app):
    created = admin_client.post(
        "/requests/new",
        data={
            "number": "26-8501",
            "address": "Связь не нужна, 1",
            "received_at": "2026-09-02T12:00",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    request_id = created.headers["Location"].rstrip("/").split("/")[-1]
    with app.app_context():
        category_id = str(db.session.scalar(db.select(DefectCategory.id).where(DefectCategory.code == "other")))
    defect = admin_client.post(
        "/defects/new",
        data={
            "number": "DF-26-85",
            "description": "Без связи",
            "category_id": category_id,
            "address": "Связь не нужна, 2",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    defect_id = defect.headers["Location"].rstrip("/").split("/")[-1]
    assert admin_client.post(f"/requests/{request_id}/defects", data={"defect_id": defect_id}).status_code == 404
    req_page = admin_client.get(f"/requests/{request_id}").get_data(as_text=True)
    def_page = admin_client.get(f"/defects/{defect_id}").get_data(as_text=True)
    assert "Связанные дефекты" not in req_page
    assert "Связанные заявки" not in def_page
    with app.app_context():
        assert db.session.get(Request, request_id) is not None
        assert db.session.get(Defect, defect_id) is not None
        assert RequestRepository.get_default_journal() is not None
        assert "RequestDefect" not in {mapper.class_.__name__ for mapper in db.Model.registry.mappers}
