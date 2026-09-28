"""Обследование объекта: опоры на карте и перенос количества в проект."""

from __future__ import annotations

import uuid

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import WorkObjectKind, WorkObjectStatus
from app.models.irz import LightPole
from app.models.work_objects.object_survey_pole import ObjectSurveyPole
from app.modules.objects.services import ObjectPayload, ObjectService
from app.modules.projects.services import ProjectPayload, ProjectService


def _admin_id():
    return db.session.scalar(db.select(User.id).where(User.email == "admin@opora.ru"))


def _object(app, address="ул. Обследования, 1"):
    with app.app_context():
        obj = ObjectService.create(
            ObjectPayload(
                name=f"Устройство наружного освещения {address}",
                work_type="Устройство наружного освещения",
                object_kind=WorkObjectKind.PLANNED.value,
                address=address,
                plan_year=2026,
                status=WorkObjectStatus.FREE.value,
                create_draft_project=False,
                latitude=None,
                longitude=None,
            ),
            _admin_id(),
        )
        return str(obj.id)


def test_object_detail_has_survey_block(admin_client, app):
    object_id = _object(app)
    page = admin_client.get(f"/objects/{object_id}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Обследование объекта" in html
    assert "object-survey.js" in html
    assert 'data-object-survey' in html
    assert "Поставить по GPS" in html


def test_survey_crud_and_does_not_write_monitoring(admin_client, app):
    object_id = _object(app, "ул. Опорная, 5")
    created = admin_client.post(
        f"/objects/{object_id}/survey/poles.json",
        json={
            "kind": "existing",
            "pole_type": "concrete",
            "lat": 58.6035,
            "lng": 49.6680,
            "source": "gps",
            "accuracy_m": 8.4,
        },
    )
    assert created.status_code == 200
    body = created.get_json()
    assert body["success"] is True
    pole_id = body["pole"]["id"]
    assert body["summary"]["total"] == 1
    assert body["pole"]["kind"] == "existing"
    assert body["pole"]["pole_type"] == "concrete"

    listed = admin_client.get(f"/objects/{object_id}/survey/poles.json")
    assert listed.status_code == 200
    assert listed.get_json()["summary"]["total"] == 1

    moved = admin_client.patch(
        f"/objects/{object_id}/survey/poles/{pole_id}.json",
        json={"lat": 58.6040, "lng": 49.6690, "kind": "planned", "source": "manual"},
    )
    assert moved.status_code == 200
    assert moved.get_json()["pole"]["kind"] == "planned"

    second = admin_client.post(
        f"/objects/{object_id}/survey/poles.json",
        json={"kind": "planned", "pole_type": "metal", "lat": 58.6050, "lng": 49.6700, "source": "manual"},
    )
    assert second.status_code == 200
    assert second.get_json()["summary"]["total"] == 2

    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(LightPole.id))) == 0
        poles = list(
            db.session.scalars(
                db.select(ObjectSurveyPole).where(
                    ObjectSurveyPole.object_id == uuid.UUID(object_id),
                    ObjectSurveyPole.active_filter(),
                )
            )
        )
        assert len(poles) == 2

    deleted = admin_client.post(f"/objects/{object_id}/survey/poles/{pole_id}/delete")
    assert deleted.status_code == 200
    assert deleted.get_json()["summary"]["total"] == 1


def test_survey_poles_count_fills_project_plan(admin_client, app):
    object_id = _object(app, "ул. План, 8")
    admin_client.post(
        f"/objects/{object_id}/survey/poles.json",
        json={"kind": "existing", "pole_type": "other", "lat": 58.61, "lng": 49.67, "source": "manual"},
    )
    admin_client.post(
        f"/objects/{object_id}/survey/poles.json",
        json={"kind": "planned", "pole_type": "metal", "lat": 58.611, "lng": 49.671, "source": "gps"},
    )
    form = admin_client.get(f"/projects/new?object_id={object_id}")
    html = form.get_data(as_text=True)
    assert "С карты обследования: 2 опор" in html
    assert 'name="poles_count"' in html
    assert "value=\"2\"" in html or "value='2'" in html

    with app.app_context():
        project = ProjectService.create_project(
            ProjectPayload(
                code="SURVEY-1",
                name="Проект обследования",
                description="",
                status="draft",
                progress_percent=0,
                start_date=None,
                end_date=None,
                responsible_id=_admin_id(),
                executor_ids=[],
                object_id=uuid.UUID(object_id),
            ),
            _admin_id(),
        )
        assert project.poles_count == 2


def test_master_cannot_edit_survey_but_can_view(client, app):
    object_id = _object(app, "ул. Мастерская, 3")
    client.post(
        "/auth/login",
        data={"email": "master@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    listed = client.get(f"/objects/{object_id}/survey/poles.json")
    assert listed.status_code == 200
    denied = client.post(
        f"/objects/{object_id}/survey/poles.json",
        json={"kind": "existing", "pole_type": "metal", "lat": 58.6, "lng": 49.6, "source": "manual"},
    )
    assert denied.status_code == 403


def test_city_poles_overlay_is_read_only(admin_client, app):
    object_id = _object(app, "ул. Мониторинг, 2")
    with app.app_context():
        db.session.add(
            LightPole(
                pole_number=f"T{uuid.uuid4().hex[:8]}",
                luminaire_name="тест",
                latitude=58.6035,
                longitude=49.668,
                quantity=1,
            )
        )
        db.session.commit()
        before = db.session.scalar(db.select(db.func.count(LightPole.id)))
    overlay = admin_client.get(
        f"/objects/{object_id}/survey/city-poles.json?bbox=49.66,58.60,49.68,58.61"
    )
    assert overlay.status_code == 200
    data = overlay.get_json()
    assert data["type"] == "FeatureCollection"
    assert data["features"]
    admin_client.post(
        f"/objects/{object_id}/survey/poles.json",
        json={"kind": "existing", "pole_type": "metal", "lat": 58.6036, "lng": 49.6681, "source": "manual"},
    )
    with app.app_context():
        after = db.session.scalar(db.select(db.func.count(LightPole.id)))
        assert after == before


def test_geolocation_allowed_for_same_origin(admin_client):
    resp = admin_client.get("/")
    policy = resp.headers.get("Permissions-Policy") or ""
    assert "geolocation=(self)" in policy
    assert "microphone=()" in policy
    assert "camera=()" in policy
