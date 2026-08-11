"""Маршруты модуля объектов."""

from __future__ import annotations

import uuid

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.models.auth.constants import (
    PERM_OBJECTS_CREATE,
    PERM_OBJECTS_DELETE,
    PERM_OBJECTS_EDIT,
    PERM_OBJECTS_VIEW,
)
from app.modules.objects.blueprint import objects_bp
from app.modules.objects.forms import OBJECT_STATUS_LABELS, ObjectFilterForm, ObjectForm
from app.modules.objects.repositories import ObjectFilter, ObjectRepository
from app.modules.objects.services import ObjectPayload, ObjectService


def _payload(form: ObjectForm) -> ObjectPayload:
    return ObjectPayload(
        name=form.name.data or "",
        address=form.address.data,
        plan_year=form.plan_year.data,
        notes=form.notes.data,
        status=form.status.data or "free",
    )


@objects_bp.route("/")
@login_required
@permission_required(PERM_OBJECTS_VIEW)
def index():
    filter_form = ObjectFilterForm(request.args)
    filters = ObjectFilter(
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        plan_year=request.args.get("plan_year", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = ObjectRepository.paginated_list(filters, page=page, per_page=per_page)
    return render_template(
        "objects/index.html",
        filter_form=filter_form,
        pagination=pagination,
        items=pagination.items,
        status_labels=OBJECT_STATUS_LABELS,
    )


@objects_bp.route("/table")
@login_required
@permission_required(PERM_OBJECTS_VIEW)
def table():
    filters = ObjectFilter(
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        plan_year=request.args.get("plan_year", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = ObjectRepository.paginated_list(filters, page=page, per_page=per_page)
    return render_template(
        "objects/partials/table.html",
        pagination=pagination,
        items=pagination.items,
        status_labels=OBJECT_STATUS_LABELS,
    )


@objects_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required(PERM_OBJECTS_CREATE)
def create():
    form = ObjectForm()
    if request.method == "GET":
        form.status.data = "free"
    if form.validate_on_submit():
        try:
            obj = ObjectService.create(_payload(form), current_user.id)
            flash("Объект создан.", "success")
            if is_ajax():
                return ajax_ok(redirect=url_for("objects.detail", object_id=obj.id))
            return redirect(url_for("objects.detail", object_id=obj.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc))
            flash(str(exc), "danger")
    elif request.method == "POST" and is_ajax():
        return ajax_error(form_errors_message(form))
    if is_ajax() and request.method == "GET":
        return render_template(
            "objects/partials/form_modal.html",
            form=form,
            form_action=url_for("objects.create"),
            modal_title="Новый объект",
        )
    return render_template("objects/form.html", form=form, mode="create")


@objects_bp.route("/<uuid:object_id>")
@login_required
@permission_required(PERM_OBJECTS_VIEW)
def detail(object_id: uuid.UUID):
    obj = ObjectRepository.get_by_id(object_id)
    if obj is None:
        flash("Объект не найден.", "danger")
        return redirect(url_for("objects.index"))
    return render_template(
        "objects/detail.html",
        obj=obj,
        status_labels=OBJECT_STATUS_LABELS,
    )


@objects_bp.route("/<uuid:object_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_OBJECTS_EDIT)
def edit(object_id: uuid.UUID):
    obj = ObjectRepository.get_by_id(object_id)
    if obj is None:
        flash("Объект не найден.", "danger")
        return redirect(url_for("objects.index"))
    form = ObjectForm(obj=obj)
    if request.method == "GET":
        form.name.data = obj.name
        form.address.data = obj.address
        form.plan_year.data = obj.plan_year
        form.notes.data = obj.notes
        form.status.data = obj.status
    if form.validate_on_submit():
        try:
            ObjectService.update(obj, _payload(form), current_user.id)
            flash("Объект сохранён.", "success")
            if is_ajax():
                return ajax_ok(redirect=url_for("objects.detail", object_id=obj.id))
            return redirect(url_for("objects.detail", object_id=obj.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc))
            flash(str(exc), "danger")
    elif request.method == "POST" and is_ajax():
        return ajax_error(form_errors_message(form))
    if is_ajax() and request.method == "GET":
        return render_template(
            "objects/partials/form_modal.html",
            form=form,
            form_action=url_for("objects.edit", object_id=obj.id),
            modal_title="Редактирование объекта",
        )
    return render_template("objects/form.html", form=form, mode="edit", obj=obj)


@objects_bp.route("/<uuid:object_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_OBJECTS_DELETE)
def delete(object_id: uuid.UUID):
    obj = ObjectRepository.get_by_id(object_id)
    if obj is None:
        flash("Объект не найден.", "danger")
        return redirect(url_for("objects.index"))
    try:
        ObjectService.soft_delete(obj, current_user.id)
        flash("Объект удалён.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("objects.detail", object_id=object_id))
    return redirect(url_for("objects.index"))
