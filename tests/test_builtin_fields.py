"""Тесты управления встроенными полями (видимость / переименование / seed)."""

from __future__ import annotations

from app.core.builtin_field_service import BuiltinFieldService
from app.core.field_catalog import list_field_builder_rows
from app.extensions import db
from app.models.auth.field_definition import FieldDefinition
from app.models.auth.system_module import SystemModule
from app.modules.requests.forms import RequestForm
from app.seed.reference_data import ReferenceDataService
from wtforms.validators import DataRequired


def _find_field(module_code: str, code: str) -> FieldDefinition:
    mod = db.session.scalar(
        db.select(SystemModule).where(
            SystemModule.code == module_code,
            SystemModule.active_filter(),
        )
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


def test_builtin_rows_are_editable(app):
    with app.app_context():
        rows = list_field_builder_rows("requests")
        builtins = [r for r in rows if r.source == "builtin"]
        assert builtins
        assert all(r.is_editable and r.field_id for r in builtins)


def test_rename_and_hide_builtin_field(app):
    with app.app_context():
        field = _find_field("requests", "phone")
        BuiltinFieldService.update_field(
            field,
            name="Контактный телефон",
            sort_order=55,
            is_visible=True,
        )
        BuiltinFieldService.clear_cache()
        assert BuiltinFieldService.label("requests", "phone") == "Контактный телефон"
        assert BuiltinFieldService.is_visible("requests", "phone") is True

        BuiltinFieldService.hide_field(field)
        BuiltinFieldService.clear_cache()
        assert BuiltinFieldService.is_visible("requests", "phone") is False


def test_seed_does_not_overwrite_manual_settings(app):
    with app.app_context():
        field = _find_field("requests", "address")
        BuiltinFieldService.update_field(
            field,
            name="Адрес объекта",
            sort_order=42,
            is_visible=False,
        )
        BuiltinFieldService.clear_cache()

        ReferenceDataService.seed_all()
        BuiltinFieldService.clear_cache()

        refreshed = _find_field("requests", "address")
        assert refreshed.name == "Адрес объекта"
        assert refreshed.sort_order == 42
        assert refreshed.is_visible is False


def test_apply_to_form_removes_required_for_hidden(app):
    with app.app_context():
        field = _find_field("requests", "address")
        BuiltinFieldService.hide_field(field)
        BuiltinFieldService.clear_cache()

        form = RequestForm()
        BuiltinFieldService.apply_to_form(form, "requests")
        assert form.address.label.text  # label still set
        assert not any(isinstance(v, DataRequired) for v in form.address.validators)
        assert BuiltinFieldService.value_or_default(
            "requests", "address", "", default="Без адреса"
        ) == "Без адреса"


def test_field_builder_edit_builtin_http(admin_client, app):
    with app.app_context():
        field = _find_field("requests", "phone")
        field_id = str(field.id)

    headers = {"X-Requested-With": "XMLHttpRequest"}
    resp = admin_client.get(f"/field-builder/builtin/{field_id}/edit", headers=headers)
    assert resp.status_code == 200
    assert b"builtinFieldForm" in resp.data

    resp = admin_client.post(
        f"/field-builder/builtin/{field_id}/edit",
        data={
            "code": "phone",
            "name": "Телефон QA",
            "is_visible": "y",
            "sort_order": "70",
            "submit": "Сохранить",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["success"] is True

    with app.app_context():
        BuiltinFieldService.clear_cache()
        assert BuiltinFieldService.label("requests", "phone") == "Телефон QA"


def test_hide_builtin_http(admin_client, app):
    with app.app_context():
        field = _find_field("projects", "description")
        field_id = str(field.id)

    resp = admin_client.post(
        f"/field-builder/builtin/{field_id}/hide",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with app.app_context():
        BuiltinFieldService.clear_cache()
        assert BuiltinFieldService.is_visible("projects", "description") is False
