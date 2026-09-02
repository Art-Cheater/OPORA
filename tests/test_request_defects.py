"""Связь заявка ↔ дефект."""

from __future__ import annotations

from app.extensions import db
from app.models.audit.audit_log import AuditLog
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.request_defect import RequestDefect
from app.models.enums import EntityType


def test_link_and_unlink_request_defect(admin_client, app):
    req_resp = admin_client.post(
        "/requests/new",
        data={
            "number": "26-4101",
            "address": "Молодой Гвардии 12",
            "received_at": "2026-09-02T11:00",
            "dispatcher_name": "Иванова А.С.",
            "applicant_name": "Тест",
            "priority": "medium",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert req_resp.status_code == 302
    request_id = req_resp.headers["Location"].rstrip("/").split("/")[-1]
    with app.app_context():
        category_id = str(db.session.scalar(db.select(DefectCategory.id).where(DefectCategory.code == "pole")))
    def_resp = admin_client.post(
        "/defects/new",
        data={
            "number": "DF-26-41",
            "description": "Треснула опора",
            "category_id": category_id,
            "address": "Молодой Гвардии 12",
            "submit": "Сохранить",
        },
        follow_redirects=False,
    )
    assert def_resp.status_code == 302
    defect_id = def_resp.headers["Location"].rstrip("/").split("/")[-1]

    linked = admin_client.post(
        f"/requests/{request_id}/defects",
        data={"defect_id": defect_id},
        follow_redirects=False,
    )
    assert linked.status_code in (200, 302)
    with app.app_context():
        pair = db.session.scalar(
            db.select(RequestDefect).where(
                RequestDefect.request_id == request_id,
                RequestDefect.defect_id == defect_id,
                RequestDefect.active_filter(),
            )
        )
        assert pair is not None
        logs = list(
            db.session.scalars(
                db.select(AuditLog).where(
                    AuditLog.action == "update",
                    AuditLog.entity_type.in_([EntityType.REQUEST.value, EntityType.DEFECT.value]),
                )
            )
        )
        assert any("дефект" in (log.description or "").lower() or "заявк" in (log.description or "").lower() for log in logs)

    unlinked = admin_client.post(
        f"/requests/{request_id}/defects/{defect_id}/unlink",
        follow_redirects=False,
    )
    assert unlinked.status_code in (200, 302)
    with app.app_context():
        pair = db.session.scalar(
            db.select(RequestDefect).where(
                RequestDefect.request_id == request_id,
                RequestDefect.defect_id == defect_id,
                RequestDefect.active_filter(),
            )
        )
        assert pair is None
        relink = admin_client.post(
            f"/defects/{defect_id}/link-request",
            data={"request_id": request_id},
            follow_redirects=False,
        )
    assert relink.status_code in (200, 302)
    with app.app_context():
        restored = db.session.scalar(
            db.select(RequestDefect).where(
                RequestDefect.request_id == request_id,
                RequestDefect.defect_id == defect_id,
                RequestDefect.active_filter(),
            )
        )
        assert restored is not None
        assert db.session.get(Defect, defect_id) is not None
