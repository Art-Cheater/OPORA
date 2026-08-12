"""Маршруты модуля объектов."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

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
from app.modules.objects.forms import OBJECT_STATUS_LABELS, ObjectFilterForm, ObjectForm, ObjectImportForm
from app.modules.objects.repositories import ObjectFilter, ObjectRepository
from app.modules.objects.services import ObjectPayload, ObjectService


def _payload(form: ObjectForm) -> ObjectPayload:
    return ObjectPayload(
        name=form.full_name.data or "",
        work_type=form.work_type.data,
        address=form.address.data,
        plan_year=form.plan_year.data,
        work_deadline=form.work_deadline.data,
        contract_number=form.contract_number.data,
        contract_date=form.contract_date.data,
        contractor_name=form.contractor_name.data,
        contract_amount=form.contract_amount.data,
        budget_amount=form.budget_amount.data,
        result_text=form.result_text.data,
        source_sheet=None,
        notes=form.notes.data,
        status=form.status.data or "free",
    )


def _render_form_modal(form: ObjectForm, form_action: str, modal_title: str):
    return render_template(
        "objects/partials/form_modal.html",
        form=form,
        form_action=form_action,
        modal_title=modal_title,
    )


@objects_bp.route("/")
@login_required
@permission_required(PERM_OBJECTS_VIEW)
def index():
    filter_form = ObjectFilterForm(request.args)
    import_form = ObjectImportForm()
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
        import_form=import_form,
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
    html = render_template(
        "objects/partials/table.html",
        pagination=pagination,
        items=pagination.items,
        status_labels=OBJECT_STATUS_LABELS,
    )
    pager = render_template(
        "objects/partials/pagination.html",
        pagination=pagination,
    )
    return jsonify({"table_html": html, "pagination_html": pager})


@objects_bp.route("/new", methods=["GET", "POST"])
@objects_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required(PERM_OBJECTS_CREATE)
def create():
    form = ObjectForm()
    if request.method == "GET":
        form.status.data = "free"
        form.work_type.data = "Устройство наружного освещения"
    if form.validate_on_submit():
        try:
            obj = ObjectService.create(_payload(form), current_user.id)
            flash("Объект создан.", "success")
            if is_ajax():
                return ajax_ok("Объект создан.", redirect_url=url_for("objects.detail", object_id=obj.id))
            return redirect(url_for("objects.detail", object_id=obj.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=_render_form_modal(form, url_for("objects.create"), "Новый объект"),
                )
            flash(str(exc), "danger")
    elif request.method == "POST" and is_ajax():
        return ajax_error(
            form_errors_message(form),
            html=_render_form_modal(form, url_for("objects.create"), "Новый объект"),
        )
    if is_ajax() and request.method == "GET":
        return _render_form_modal(form, url_for("objects.create"), "Новый объект")
    return render_template("objects/form.html", form=form, mode="create")


@objects_bp.route("/import", methods=["POST"])
@login_required
@permission_required(PERM_OBJECTS_CREATE)
def import_plan():
    form = ObjectImportForm()
    if not form.validate_on_submit():
        flash(form_errors_message(form) or "Выберите файл Excel (.xlsx).", "danger")
        return redirect(url_for("objects.index"))

    upload = form.file.data
    filename = secure_filename(upload.filename or "plan.xlsx")
    if not filename.lower().endswith(".xlsx"):
        flash("Нужен файл формата .xlsx.", "danger")
        return redirect(url_for("objects.index"))

    upload_dir = Path(current_app.instance_path) / "imports"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = upload_dir / f"{uuid.uuid4().hex}_{filename}"
    try:
        upload.save(tmp_path)
        result = ObjectService.import_from_lighting_plan(tmp_path, current_user.id)
        flash(
            f"Импорт завершён: создано {result.created}, обновлено {result.updated}, "
            f"пропущено {result.skipped} (всего строк с названиями: {result.total}).",
            "success",
        )
    except ValidationError as exc:
        flash(str(exc), "danger")
    except Exception as exc:  # noqa: BLE001 — показать пользователю понятную ошибку файла
        current_app.logger.exception("Ошибка импорта объектов")
        flash(f"Не удалось импортировать файл: {exc}", "danger")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return redirect(url_for("objects.index"))


@objects_bp.route("/wipe", methods=["POST"])
@login_required
@permission_required(PERM_OBJECTS_DELETE)
def wipe():
    """Мягко удалить все объекты — перед повторным импортом из Excel."""
    count = ObjectService.wipe_all(current_user.id)
    flash(f"Удалено объектов: {count}. Можно заново импортировать файл.", "success")
    return redirect(url_for("objects.index"))


@objects_bp.route("/<uuid:object_id>")
@login_required
@permission_required(PERM_OBJECTS_VIEW)
def detail(object_id: uuid.UUID):
    from app.extensions import db
    from app.models.enums import ProjectStatus
    from app.models.projects.project import Project

    obj = ObjectRepository.get_by_id(object_id)
    if obj is None:
        flash("Объект не найден.", "danger")
        return redirect(url_for("objects.index"))

    has_active_project = (
        db.session.scalar(
            db.select(Project.id).where(
                Project.object_id == obj.id,
                Project.active_filter(),
                Project.status.notin_(
                    [
                        ProjectStatus.COMPLETED.value,
                        ProjectStatus.CANCELLED.value,
                        ProjectStatus.ARCHIVED.value,
                    ]
                ),
            ).limit(1)
        )
        is not None
    )
    suggested = ObjectService.suggested_project_status(obj.result_text)
    can_create_project = (not has_active_project) and obj.status not in (
        "in_tender",
        "completed",
        "archived",
    )
    can_create_contract = ObjectService.can_create_contract_from_plan(obj)
    ctx = {
        "obj": obj,
        "status_labels": OBJECT_STATUS_LABELS,
        "suggested_project_status": suggested,
        "can_create_project": can_create_project,
        "can_create_contract": can_create_contract,
    }
    if is_ajax() and not request.args.get("full"):
        return render_template("objects/partials/detail_modal.html", **ctx)
    return render_template("objects/detail.html", **ctx)


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
        form.work_type.data = obj.work_type or "Устройство наружного освещения"
        form.address.data = obj.address or obj.name
        form.full_name.data = obj.name
        form.plan_year.data = obj.plan_year
        form.work_deadline.data = obj.work_deadline
        form.contract_number.data = obj.contract_number
        form.contract_date.data = obj.contract_date
        form.contractor_name.data = obj.contractor_name
        form.contract_amount.data = obj.contract_amount
        form.budget_amount.data = obj.budget_amount
        form.result_text.data = obj.result_text
        form.notes.data = obj.notes
        form.status.data = obj.status
    if form.validate_on_submit():
        try:
            ObjectService.update(obj, _payload(form), current_user.id)
            flash("Объект сохранён.", "success")
            if is_ajax():
                return ajax_ok(
                    "Объект сохранён.",
                    redirect_url=url_for("objects.detail", object_id=obj.id),
                )
            return redirect(url_for("objects.detail", object_id=obj.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=_render_form_modal(
                        form, url_for("objects.edit", object_id=obj.id), "Редактирование объекта"
                    ),
                )
            flash(str(exc), "danger")
    elif request.method == "POST" and is_ajax():
        return ajax_error(
            form_errors_message(form),
            html=_render_form_modal(
                form, url_for("objects.edit", object_id=obj.id), "Редактирование объекта"
            ),
        )
    if is_ajax() and request.method == "GET":
        return _render_form_modal(
            form, url_for("objects.edit", object_id=obj.id), "Редактирование объекта"
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
        if is_ajax():
            return ajax_ok("Объект удалён.")
    except ValidationError as exc:
        if is_ajax():
            return ajax_error(str(exc))
        flash(str(exc), "danger")
        return redirect(url_for("objects.detail", object_id=object_id))
    return redirect(url_for("objects.index"))
