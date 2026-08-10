"""Маршруты модуля ролей."""

from __future__ import annotations

import uuid

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.core.permission_service import FIELD_ACCESS_LABELS, MODULE_ACTION_LABELS, PermissionService
from app.models.auth.constants import PERM_ROLES_MANAGE, PERM_ROLES_VIEW, ROLE_ADMIN
from app.models.auth.field_registry import get_module_fields, get_module_labels
from app.models.auth.role_field_permission import FIELD_ACCESS_EDIT, FIELD_ACCESS_NONE
from app.modules.roles.blueprint import roles_bp
from app.modules.roles.forms import RoleFilterForm, RoleForm
from app.modules.roles.repositories import RoleFilter, RoleRepository
from app.modules.roles.services import FieldRulePayload, RolePayload, RoleService


def _uuid_list(values: list[str]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for value in values or []:
        try:
            result.append(uuid.UUID(value))
        except ValueError:
            continue
    return result


def _parse_field_rules() -> list[FieldRulePayload]:
    rules: list[FieldRulePayload] = []
    module_fields = get_module_fields()
    for module, fields in module_fields.items():
        for field_name in fields:
            raw = request.form.get(f"field_level_{module}_{field_name}", "0")
            try:
                level = int(raw)
            except ValueError:
                level = FIELD_ACCESS_NONE
            if level > FIELD_ACCESS_NONE:
                rules.append(
                    FieldRulePayload(
                        module=module,
                        field_name=field_name,
                        access_level=level,
                    )
                )
    return rules


def _payload_from_form(form: RoleForm) -> RolePayload:
    return RolePayload(
        code=form.code.data or "",
        name=form.name.data or "",
        description=form.description.data,
        permission_ids=_uuid_list(request.form.getlist("permission_ids")),
        field_rules=_parse_field_rules(),
    )


def _permissions_matrix():
    return PermissionService.get_permissions_matrix()


def _permission_rows(permissions_matrix, modules, standard_actions):
    """Строки матрицы прав: стандартные колонки + дополнительные права модуля."""
    rows: list[dict] = []
    for mod in modules:
        mod_perms = permissions_matrix.get(mod.code)
        if not mod_perms:
            continue
        rows.append(
            {
                "module": mod,
                "standard": {action: mod_perms[action] for action in standard_actions if action in mod_perms},
                "extra": [(action, mod_perms[action]) for action in mod_perms if action not in standard_actions],
            }
        )
    return rows


def _field_rules_map(role=None) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for module, fields in get_module_fields().items():
        result[module] = {name: FIELD_ACCESS_NONE for name in fields}
    if role is None:
        return result
    for rule in RoleRepository.get_field_rules(role):
        bucket = result.setdefault(rule.module, {})
        bucket[rule.field_name] = rule.access_level
    return result


def _editor_context(role=None, form=None, form_action=None, is_edit=False):
    permissions_matrix = _permissions_matrix()
    standard_actions = frozenset(MODULE_ACTION_LABELS.keys())
    modules = PermissionService.get_modules()
    module_fields = get_module_fields()
    selected_permission_ids = {
        str(pid) for pid in (RoleRepository.get_permission_ids(role) if role else [])
    }
    field_rules_map = _field_rules_map(role)

    if role is not None and role.code == ROLE_ADMIN:
        selected_permission_ids = {
            str(perm.id) for mod_perms in permissions_matrix.values() for perm in mod_perms.values()
        }
        field_rules_map = {
            module: {field_name: FIELD_ACCESS_EDIT for field_name in fields}
            for module, fields in module_fields.items()
        }

    return dict(
        form=form,
        form_action=form_action,
        role=role,
        is_edit=is_edit,
        modules=modules,
        permissions_matrix=permissions_matrix,
        permission_rows=_permission_rows(permissions_matrix, modules, standard_actions),
        module_actions=MODULE_ACTION_LABELS,
        module_labels=get_module_labels(),
        module_fields=module_fields,
        selected_permission_ids=selected_permission_ids,
        field_rules_map=field_rules_map,
        field_access_labels=FIELD_ACCESS_LABELS,
        can_manage=current_user.has_permission(PERM_ROLES_MANAGE),
        is_admin_role=bool(role and role.code == ROLE_ADMIN),
        standard_actions=standard_actions,
    )


@roles_bp.route("/")
@login_required
@permission_required(PERM_ROLES_VIEW)
def index():
    filter_form = RoleFilterForm(request.args)
    roles = RoleRepository.list_all(
        RoleFilter(
            q=request.args.get("q", ""),
            sort_by=request.args.get("sort_by", "name"),
            sort_dir=request.args.get("sort_dir", "asc"),
        )
    )
    selected_id = request.args.get("role_id")
    selected = RoleRepository.get_by_id(selected_id) if selected_id else (roles[0] if roles else None)

    if selected:
        form = RoleForm(obj=selected)
        form.is_edit = True
        form.is_system = selected.is_system
        form_action = url_for("roles.edit", role_id=selected.id)
        is_edit = True
    else:
        form = RoleForm()
        form.is_edit = False
        form_action = url_for("roles.create")
        is_edit = False

    ctx = _editor_context(
        role=selected,
        form=form,
        form_action=form_action,
        is_edit=is_edit,
    )
    return render_template(
        "roles/index.html",
        filter_form=filter_form,
        roles=roles,
        selected_role=selected,
        **ctx,
    )


@roles_bp.route("/editor/<uuid:role_id>")
@login_required
@permission_required(PERM_ROLES_VIEW)
def editor(role_id: uuid.UUID):
    role = RoleRepository.get_by_id(role_id)
    if role is None:
        return ajax_error("Роль не найдена.", status=404)
    form = RoleForm(obj=role)
    form.is_edit = True
    form.is_system = role.is_system
    html = render_template(
        "roles/partials/role_editor.html",
        **_editor_context(
            role=role,
            form=form,
            form_action=url_for("roles.edit", role_id=role.id),
            is_edit=True,
        ),
    )
    return jsonify({"html": html, "role_id": str(role.id)})


@roles_bp.route("/editor/new")
@login_required
@permission_required(PERM_ROLES_MANAGE)
def editor_new():
    form = RoleForm()
    form.is_edit = False
    html = render_template(
        "roles/partials/role_editor.html",
        **_editor_context(
            role=None,
            form=form,
            form_action=url_for("roles.create"),
            is_edit=False,
        ),
    )
    return jsonify({"html": html})


@roles_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_ROLES_MANAGE)
def create():
    form = RoleForm()
    form.is_edit = False

    if form.validate_on_submit():
        try:
            created = RoleService.create_role(_payload_from_form(form), current_user.id)
            if is_ajax():
                return ajax_ok("Роль успешно создана.", id=str(created.id))
            flash("Роль успешно создана.", "success")
            return redirect(url_for("roles.index", role_id=created.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc))
            flash(str(exc), "danger")
    elif request.method == "POST":
        return ajax_error(form_errors_message(form))

    if is_ajax():
        return render_template("roles/partials/role_editor.html", **_editor_context(form=form, form_action=url_for("roles.create")))
    return redirect(url_for("roles.index"))


@roles_bp.route("/<uuid:role_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_ROLES_MANAGE)
def edit(role_id: uuid.UUID):
    role = RoleRepository.get_by_id(role_id)
    if role is None:
        flash("Роль не найдена.", "danger")
        return redirect(url_for("roles.index"))

    form = RoleForm(obj=role)
    form.is_edit = True
    form.is_system = role.is_system

    if form.validate_on_submit():
        try:
            RoleService.update_role(role, _payload_from_form(form), current_user.id)
            if is_ajax():
                return ajax_ok("Роль обновлена.", id=str(role.id))
            flash("Роль обновлена.", "success")
            return redirect(url_for("roles.index", role_id=role.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc))
            flash(str(exc), "danger")
    elif request.method == "POST":
        return ajax_error(form_errors_message(form))

    if is_ajax():
        return render_template(
            "roles/partials/role_editor.html",
            **_editor_context(role=role, form=form, form_action=url_for("roles.edit", role_id=role.id), is_edit=True),
        )
    return redirect(url_for("roles.index", role_id=role.id))


@roles_bp.route("/<uuid:role_id>/duplicate", methods=["POST"])
@login_required
@permission_required(PERM_ROLES_MANAGE)
def duplicate(role_id: uuid.UUID):
    role = RoleRepository.get_by_id(role_id)
    if role is None:
        return ajax_error("Роль не найдена.", status=404)
    try:
        created = RoleService.duplicate_role(role, current_user.id)
        return ajax_ok("Роль продублирована.", id=str(created.id))
    except ValidationError as exc:
        return ajax_error(str(exc))


@roles_bp.route("/<uuid:role_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_ROLES_MANAGE)
def delete(role_id: uuid.UUID):
    role = RoleRepository.get_by_id(role_id)
    if role is None:
        return ajax_error("Роль не найдена.", status=404)
    try:
        RoleService.delete_role(role, current_user.id)
        return ajax_ok("Роль удалена.")
    except ValidationError as exc:
        return ajax_error(str(exc))
