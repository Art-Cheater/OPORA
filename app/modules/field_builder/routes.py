"""Маршруты конструктора полей."""

from __future__ import annotations

import uuid

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.field_catalog import list_field_builder_rows
from app.core.custom_field_service import CustomFieldService, CustomFieldPayload, OptionPayload
from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.models.auth.constants import PERM_ROLES_MANAGE
from app.models.custom_fields.constants import CUSTOM_FIELD_MODULE_LABELS, FIELD_TYPE_LABELS
from app.modules.field_builder.blueprint import field_builder_bp
from app.modules.field_builder.forms import CustomFieldForm


def _parse_options(text: str) -> list[OptionPayload]:
    options: list[OptionPayload] = []
    for idx, line in enumerate((text or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            value, label = line.split("|", 1)
        else:
            value, label = line, line
        options.append(OptionPayload(value=value.strip(), label=label.strip(), sort_order=idx * 10))
    return options


def _payload_from_form(form: CustomFieldForm) -> CustomFieldPayload:
    return CustomFieldPayload(
        module_code=form.module_code.data,
        code=form.code.data or "",
        name=form.name.data or "",
        field_type=form.field_type.data,
        description=form.description.data,
        is_required=bool(form.is_required.data),
        is_visible=bool(form.is_visible.data) if form.is_visible.data is not None else True,
        sort_order=form.sort_order.data or 0,
        options=_parse_options(form.options_text.data or ""),
    )


def _options_to_text(field) -> str:
    lines = []
    for opt in field.options:
        if opt.deleted_at is None:
            lines.append(f"{opt.value}|{opt.label}")
    return "\n".join(lines)


@field_builder_bp.route("/")
@login_required
@permission_required(PERM_ROLES_MANAGE)
def index():
    module_code = request.args.get("module", "requests")
    if module_code not in CUSTOM_FIELD_MODULE_LABELS:
        module_code = "requests"
    fields = list_field_builder_rows(module_code)
    return render_template(
        "field_builder/index.html",
        fields=fields,
        module_code=module_code,
        module_labels=CUSTOM_FIELD_MODULE_LABELS,
        type_labels={**FIELD_TYPE_LABELS, "builtin": "Встроенное"},
    )


@field_builder_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_ROLES_MANAGE)
def create():
    form = CustomFieldForm()
    form.is_edit = False
    form.is_visible.data = True
    if request.args.get("module"):
        form.module_code.data = request.args.get("module")

    if form.validate_on_submit():
        try:
            created = CustomFieldService.create_field(_payload_from_form(form), current_user.id)
            if is_ajax():
                return ajax_ok("Поле создано.", id=str(created.id))
            flash("Поле создано.", "success")
            return redirect(url_for("field_builder.index", module=created.system_module.code))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc), html=_render_form(form, url_for("field_builder.create")))
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(form_errors_message(form), html=_render_form(form, url_for("field_builder.create")))

    if is_ajax():
        return _render_form(form, url_for("field_builder.create"))
    return redirect(url_for("field_builder.index"))


@field_builder_bp.route("/<uuid:field_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_ROLES_MANAGE)
def edit(field_id: uuid.UUID):
    field = CustomFieldService.get_by_id(field_id)
    if field is None:
        flash("Поле не найдено.", "danger")
        return redirect(url_for("field_builder.index"))

    form = CustomFieldForm(obj=field)
    form.is_edit = True
    if request.method == "GET":
        form.module_code.data = field.system_module.code
        form.options_text.data = _options_to_text(field)

    if form.validate_on_submit():
        try:
            CustomFieldService.update_field(field, _payload_from_form(form), current_user.id)
            if is_ajax():
                return ajax_ok("Поле обновлено.", id=str(field.id))
            flash("Поле обновлено.", "success")
            return redirect(url_for("field_builder.index", module=field.system_module.code))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc), html=_render_form(form, url_for("field_builder.edit", field_id=field.id), field))
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(
            form_errors_message(form),
            html=_render_form(form, url_for("field_builder.edit", field_id=field.id), field),
        )

    if is_ajax():
        return _render_form(form, url_for("field_builder.edit", field_id=field.id), field)
    return redirect(url_for("field_builder.index", module=field.system_module.code))


@field_builder_bp.route("/<uuid:field_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_ROLES_MANAGE)
def delete(field_id: uuid.UUID):
    field = CustomFieldService.get_by_id(field_id)
    if field is None:
        return ajax_error("Поле не найдено.", status=404)
    try:
        CustomFieldService.delete_field(field, current_user.id)
        return ajax_ok("Поле удалено.")
    except ValidationError as exc:
        return ajax_error(str(exc))


def _render_form(form, form_action, field=None):
    return render_template(
        "field_builder/partials/form_modal.html",
        form=form,
        form_action=form_action,
        field=field,
        is_edit=form.is_edit,
        type_labels=FIELD_TYPE_LABELS,
    )
