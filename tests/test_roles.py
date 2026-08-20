"""Сохранение ролей не должно переписывать права по одному запросу."""

from __future__ import annotations

from app.core.performance import count_queries
from app.extensions import db
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.auth.user import User
from app.modules.roles.repositories import RoleRepository
from app.modules.roles.services import FieldRulePayload, RolePayload, RoleService


def test_roles_index_opens_without_editor(admin_client):
    resp = admin_client.get("/roles/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Загрузка прав роли" in html
    assert "permission_ids" not in html


def test_roles_editor_and_save(admin_client, app):
    with app.app_context():
        role = db.session.scalar(db.select(Role).where(Role.code == "dispatcher"))
        assert role is not None
        role_id = role.id
        perms = list(
            db.session.scalars(
                db.select(Permission.id).where(
                    Permission.active_filter(),
                    Permission.code.in_(["requests.view", "requests.edit", "inquiries.view"]),
                )
            )
        )

    editor = admin_client.get(f"/roles/editor/{role_id}")
    assert editor.status_code == 200
    payload = editor.get_json()
    assert payload and "html" in payload
    assert "permission_ids" in payload["html"]

    ajax = {"X-Requested-With": "XMLHttpRequest"}
    with app.app_context():
        with count_queries(db.engine) as counter:
            saved = admin_client.post(
                f"/roles/{role_id}/edit",
                data={
                    "code": "dispatcher",
                    "name": "Диспетчер",
                    "description": "тест",
                    "permission_ids": [str(pid) for pid in perms],
                },
                headers=ajax,
            )
        assert saved.status_code == 200, saved.get_data(as_text=True)[:1000]
        body = saved.get_json()
        assert body and body.get("success") is True
        assert counter.count <= 25

        ids = {str(pid) for pid in RoleRepository.get_permission_ids(role)}
        assert {str(pid) for pid in perms} <= ids


def test_role_field_rules_diff_does_not_rewrite_unchanged(app):
    with app.app_context():
        actor = db.session.scalar(db.select(User.id).where(User.email == "admin@opora.ru"))
        dispatcher = db.session.scalar(db.select(Role).where(Role.code == "dispatcher"))
        assert dispatcher is not None
        payload = RolePayload(
            code=dispatcher.code,
            name=dispatcher.name,
            description=dispatcher.description,
            permission_ids=RoleRepository.get_permission_ids(dispatcher),
            field_rules=[
                FieldRulePayload(module="requests", field_name="address", access_level=2),
            ],
        )
        RoleService.update_role(dispatcher, payload, actor)
        with count_queries(db.engine) as counter:
            RoleService.update_role(dispatcher, payload, actor)
        assert counter.count <= 12
