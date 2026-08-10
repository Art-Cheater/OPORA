"""Маршруты модуля сотрудников."""

from __future__ import annotations

import uuid

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.custom_fields_integration import (
    custom_field_detail_context,
    custom_field_form_context,
    save_custom_fields,
)
from app.core.decorators import permission_required
from app.core.field_permissions import FieldPermissionService
from app.core.exceptions import ValidationError
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.models.auth.constants import (
    PERM_USERS_CREATE,
    PERM_USERS_DELETE,
    PERM_USERS_EDIT,
    PERM_USERS_VIEW,
    ROLE_EXECUTOR,
)
from app.modules.employees.blueprint import employees_bp
from app.modules.employees.forms import EmployeeFilterForm, EmployeeForm
from app.modules.employees.repositories import EmployeeFilter, EmployeeRepository
from app.modules.employees.services import EmployeePayload, EmployeeService


def _uuid_list(values: list[str]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for value in values or []:
        try:
            result.append(uuid.UUID(value))
        except ValueError:
            continue
    return result


def _prepare_filter_form(form: EmployeeFilterForm) -> None:
    roles = EmployeeRepository.get_roles()
    form.role_id.choices = [("", "Все роли")] + [(str(r.id), r.name) for r in roles]


def _prepare_employee_form(form: EmployeeForm) -> None:
    from app.core.builtin_field_service import BuiltinFieldService

    roles = EmployeeRepository.get_roles()
    form.role_ids.choices = [(str(r.id), r.name) for r in roles]
    positions = EmployeeRepository.get_positions()
    form.position_id.choices = [("", "—")] + [(str(p.id), p.name) for p in positions]
    BuiltinFieldService.apply_to_form(form, "users")


def _apply_employee_create_defaults(form: EmployeeForm) -> None:
    if request.method != "GET":
        return
    form.department.data = "Основное подразделение"
    positions = EmployeeRepository.get_positions()
    default_pos = next((p for p in positions if p.code == "employee"), positions[0] if positions else None)
    if default_pos is not None:
        form.position_id.data = str(default_pos.id)
    roles = EmployeeRepository.get_roles()
    default = next((r for r in roles if r.code == ROLE_EXECUTOR), roles[0] if roles else None)
    if default is not None:
        form.role_ids.data = [str(default.id)]


def _uuid_or_none(value: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _payload_from_form(form: EmployeeForm, employee=None) -> EmployeePayload:
    fp = FieldPermissionService.resolve_field
    u, m = current_user, "users"
    role_ids = _uuid_list(form.role_ids.data or [])
    if employee and not FieldPermissionService.can_edit_field(u, m, "role_ids"):
        role_ids = EmployeeRepository.get_role_ids(employee)
    password = form.password.data or None
    if employee and not FieldPermissionService.can_edit_field(u, m, "password"):
        password = None
    pos_id = _uuid_or_none(form.position_id.data or "")
    if employee and not FieldPermissionService.can_edit_field(u, m, "position_id"):
        pos_id = employee.position_id
    return EmployeePayload(
        email=fp(u, m, "email", form.email.data, employee),
        full_name=fp(u, m, "full_name", form.full_name.data, employee),
        phone=fp(u, m, "phone", form.phone.data, employee),
        position_id=pos_id,
        department=fp(u, m, "department", form.department.data, employee),
        role_ids=role_ids,
        password=password,
    )


@employees_bp.route("/")
@login_required
@permission_required(PERM_USERS_VIEW)
def index():
    filter_form = EmployeeFilterForm(request.args)
    _prepare_filter_form(filter_form)

    filters = EmployeeFilter(
        q=request.args.get("q", ""),
        role_id=request.args.get("role_id", ""),
        status=request.args.get("status", ""),
        department=request.args.get("department", ""),
        sort_by=request.args.get("sort_by", "full_name"),
        sort_dir=request.args.get("sort_dir", "asc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = EmployeeRepository.paginated_list(filters, page=page, per_page=per_page)

    return render_template(
        "employees/index.html",
        filter_form=filter_form,
        employees_pagination=pagination,
    )


@employees_bp.route("/table")
@login_required
@permission_required(PERM_USERS_VIEW)
def table():
    filters = EmployeeFilter(
        q=request.args.get("q", ""),
        role_id=request.args.get("role_id", ""),
        status=request.args.get("status", ""),
        department=request.args.get("department", ""),
        sort_by=request.args.get("sort_by", "full_name"),
        sort_dir=request.args.get("sort_dir", "asc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = EmployeeRepository.paginated_list(filters, page=page, per_page=per_page)
    html = render_template("employees/partials/table.html", employees_pagination=pagination)
    pager = render_template("employees/partials/pagination.html", employees_pagination=pagination)
    return jsonify({"table_html": html, "pagination_html": pager})


_CF = "users"


def _cf_form(entity_id=None):
    return custom_field_form_context(_CF, entity_id)


@employees_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_USERS_CREATE)
def create():
    form = EmployeeForm()
    form.is_edit = False
    _prepare_employee_form(form)
    _apply_employee_create_defaults(form)

    if form.validate_on_submit():
        try:
            created = EmployeeService.create_employee(_payload_from_form(form), current_user.id)
            save_custom_fields(_CF, created.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Сотрудник успешно создан.", id=str(created.id))
            flash("Сотрудник успешно создан.", "success")
            return redirect(url_for("employees.detail", employee_id=created.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=render_template(
                        "employees/partials/form_modal.html",
                        form=form,
                        form_action=url_for("employees.create"),
                        **_cf_form(),
                        is_edit=False,
                    ),
                )
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(
            form_errors_message(form),
            html=render_template(
                "employees/partials/form_modal.html",
                form=form,
                form_action=url_for("employees.create"),
                        **_cf_form(),
                is_edit=False,
            ),
        )

    if is_ajax():
        return render_template(
            "employees/partials/form_modal.html",
            form=form,
            form_action=url_for("employees.create"),
                        **_cf_form(),
            is_edit=False,
        )
    return render_template("employees/form.html", form=form, mode="create")


@employees_bp.route("/<uuid:employee_id>")
@login_required
@permission_required(PERM_USERS_VIEW)
def detail(employee_id: uuid.UUID):
    employee = EmployeeRepository.get_by_id(employee_id)
    if employee is None:
        flash("Сотрудник не найден.", "danger")
        return redirect(url_for("employees.index"))

    if is_ajax():
        return render_template(
            "employees/partials/detail_modal.html",
            employee=employee,
            **custom_field_detail_context(_CF, employee.id, current_user),
        )

    return render_template("employees/detail.html", employee=employee)


@employees_bp.route("/<uuid:employee_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_USERS_EDIT)
def edit(employee_id: uuid.UUID):
    employee = EmployeeRepository.get_by_id(employee_id)
    if employee is None:
        flash("Сотрудник не найден.", "danger")
        return redirect(url_for("employees.index"))

    form = EmployeeForm(obj=employee)
    form.is_edit = True
    _prepare_employee_form(form)
    if request.method == "GET":
        form.role_ids.data = [str(rid) for rid in EmployeeRepository.get_role_ids(employee)]
        form.position_id.data = str(employee.position_id) if employee.position_id else ""

    if form.validate_on_submit():
        try:
            EmployeeService.update_employee(employee, _payload_from_form(form, employee), current_user.id)
            save_custom_fields(_CF, employee.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Сотрудник обновлён.", id=str(employee.id))
            flash("Сотрудник обновлён.", "success")
            return redirect(url_for("employees.detail", employee_id=employee.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=render_template(
                        "employees/partials/form_modal.html",
                        form=form,
                        form_action=url_for("employees.edit", employee_id=employee.id),
                        **_cf_form(employee.id),
                        is_edit=True,
                    ),
                )
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(
            form_errors_message(form),
            html=render_template(
                "employees/partials/form_modal.html",
                form=form,
                form_action=url_for("employees.edit", employee_id=employee.id),
                        **_cf_form(employee.id),
                is_edit=True,
            ),
        )

    if is_ajax():
        return render_template(
            "employees/partials/form_modal.html",
            form=form,
            form_action=url_for("employees.edit", employee_id=employee.id),
                        **_cf_form(employee.id),
            is_edit=True,
        )
    return render_template("employees/form.html", form=form, mode="edit", employee=employee)


@employees_bp.route("/<uuid:employee_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_USERS_DELETE)
def delete(employee_id: uuid.UUID):
    employee = EmployeeRepository.get_by_id(employee_id)
    if employee is None:
        return ajax_error("Сотрудник не найден.", status=404)
    try:
        EmployeeService.delete_employee(employee, current_user.id)
        return ajax_ok("Сотрудник удалён.")
    except ValidationError as exc:
        return ajax_error(str(exc))
