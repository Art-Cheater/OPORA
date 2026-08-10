"""HTTP-тесты действий конструктора полей (edit/hide/delete)."""

from __future__ import annotations

from app.core.builtin_field_service import BuiltinFieldService
from app.core.custom_field_service import CustomFieldService
from app.extensions import db
from app.models.auth.field_definition import FieldDefinition
from app.models.auth.system_module import SystemModule
from app.models.custom_fields.custom_field import CustomField


AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _builtin(module_code: str, code: str) -> FieldDefinition:
    mod = db.session.scalar(
        db.select(SystemModule).where(SystemModule.code == module_code, SystemModule.active_filter())
    )
    assert mod is not None
    field = db.session.scalar(
        db.select(FieldDefinition).where(
            FieldDefinition.module_id == mod.id,
            FieldDefinition.code == code,
            FieldDefinition.active_filter(),
        )
    )
    assert field is not None
    return field


def test_index_shows_action_buttons(admin_client):
    resp = admin_client.get("/field-builder/?module=requests")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "data-opora-edit=" in html
    assert "data-opora-delete=" in html
    assert "Скрыть" in html
    assert "field-builder.js" in html
    assert "oporaFieldBuilderPage" in html


def test_builtin_hide_and_show_via_edit(admin_client, app):
    with app.app_context():
        field = _builtin("requests", "phone")
        field_id = str(field.id)

    hide = admin_client.post(
        f"/field-builder/builtin/{field_id}/hide",
        headers=AJAX,
    )
    assert hide.status_code == 200
    assert hide.get_json()["success"] is True

    with app.app_context():
        BuiltinFieldService.clear_cache()
        assert BuiltinFieldService.is_visible("requests", "phone") is False

    show = admin_client.post(
        f"/field-builder/builtin/{field_id}/edit",
        data={
            "code": "phone",
            "name": "Телефон",
            "is_visible": "y",
            "sort_order": "70",
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert show.status_code == 200
    assert show.get_json()["success"] is True

    with app.app_context():
        BuiltinFieldService.clear_cache()
        assert BuiltinFieldService.is_visible("requests", "phone") is True


def test_custom_field_create_edit_delete_without_module_in_post(admin_client, app):
    """Регресс: disabled module_code не ломает сохранение при редактировании."""
    create = admin_client.post(
        "/field-builder/new",
        data={
            "module_code": "requests",
            "code": "qa_extra_note",
            "name": "Заметка QA",
            "field_type": "text",
            "description": "",
            "is_visible": "y",
            "sort_order": "200",
            "options_text": "",
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert create.status_code == 200
    created = create.get_json()
    assert created["success"] is True
    field_id = created["id"]

    # GET формы редактирования
    edit_get = admin_client.get(f"/field-builder/{field_id}/edit", headers=AJAX)
    assert edit_get.status_code == 200
    assert b"customFieldForm" in edit_get.data
    assert b'name="module_code"' in edit_get.data  # hidden fallback

    # POST без явного module в select (как disabled) — только hidden
    edit_post = admin_client.post(
        f"/field-builder/{field_id}/edit",
        data={
            "module_code": "requests",
            "code": "qa_extra_note",
            "name": "Заметка QA обновлена",
            "field_type": "text",
            "description": "upd",
            "is_visible": "y",
            "sort_order": "210",
            "options_text": "",
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert edit_post.status_code == 200, edit_post.get_data(as_text=True)
    assert edit_post.get_json()["success"] is True

    with app.app_context():
        field = CustomFieldService.get_by_id(field_id)
        assert field is not None
        assert field.name == "Заметка QA обновлена"

    delete = admin_client.post(f"/field-builder/{field_id}/delete", headers=AJAX)
    assert delete.status_code == 200
    assert delete.get_json()["success"] is True

    with app.app_context():
        assert CustomFieldService.get_by_id(field_id) is None or (
            CustomFieldService.get_by_id(field_id) is not None
            and CustomFieldService.get_by_id(field_id).deleted_at is not None
        )


def test_custom_edit_works_when_module_omitted(admin_client, app):
    """Имитация disabled select: module_code не передаём в POST."""
    create = admin_client.post(
        "/field-builder/new",
        data={
            "module_code": "projects",
            "code": "qa_proj_flag",
            "name": "Флаг",
            "field_type": "text",
            "is_visible": "y",
            "sort_order": "10",
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    field_id = create.get_json()["id"]

    edit_post = admin_client.post(
        f"/field-builder/{field_id}/edit",
        data={
            # module_code намеренно отсутствует
            "code": "qa_proj_flag",
            "name": "Флаг 2",
            "field_type": "text",
            "is_visible": "y",
            "sort_order": "11",
            "submit": "Сохранить",
        },
        headers=AJAX,
    )
    assert edit_post.status_code == 200
    body = edit_post.get_json()
    assert body["success"] is True, body

    with app.app_context():
        field = db.session.get(CustomField, field_id)
        # soft-deleted not expected; reload via service
        field = CustomFieldService.get_by_id(field_id)
        assert field is not None
        assert field.name == "Флаг 2"
