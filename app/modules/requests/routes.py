"""Маршруты модуля заявок."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app.core.custom_fields_integration import (
    custom_field_detail_context,
    custom_field_form_context,
    save_custom_fields,
)
from app.core.decorators import any_permission_required, permission_required
from app.core.exceptions import NotFoundError, ValidationError
from app.core.field_permissions import FieldPermissionService
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.core.upload_utils import resolve_download_filename
from app.extensions import db
from app.models.auth.constants import (
    PERM_REQUESTS_APPROVE,
    PERM_REQUESTS_CREATE,
    PERM_REQUESTS_DELETE,
    PERM_REQUESTS_DISPATCH,
    PERM_REQUESTS_EDIT,
    PERM_REQUESTS_VIEW,
)
from app.models.auth.user import User
from app.models.communication.comment import Comment
from app.models.enums import Priority
from app.models.files.attachment import Attachment
from app.modules.requests.blueprint import requests_bp
from app.modules.requests.forms import (
    AssignMasterForm,
    RequestAttachmentForm,
    RequestCommentForm,
    RequestFilterForm,
    RequestForm,
    RequestMaterialForm,
)
from app.modules.requests.repositories import RequestFilter, RequestRepository
from app.modules.requests.services import RequestPayload, RequestService
from app.modules.requests.workflow import (
    STATUS_NEW,
    available_actions,
    lifecycle_progress,
)


def _uuid_or_none(value: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _resolve_uuid_field(field_name: str, form_value: str, entity=None):
    val = FieldPermissionService.resolve_field(
        current_user, "requests", field_name, form_value, entity
    )
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    return _uuid_or_none(str(val))


def _request_payload_from_form(form: RequestForm, entity=None) -> RequestPayload:
    from datetime import datetime, timezone

    from app.core.builtin_field_service import BuiltinFieldService as BFS
    from app.models.enums import Priority

    fp = FieldPermissionService.resolve_field
    u, m = current_user, "requests"

    def field(code, submitted, default=None):
        raw = fp(u, m, code, submitted, entity)
        return BFS.value_or_default(m, code, raw, default=default, entity=entity)

    if entity is not None:
        status_id = entity.status_id
    else:
        status = RequestRepository.get_status_by_code(STATUS_NEW)
        if status is None:
            raise ValueError("Статус «Новая» не найден. Выполните миграцию/сиды.")
        status_id = status.id

    address = field("address", form.address.data, default="") or ""
    received_at = field(
        "received_at",
        form.received_at.data,
        default=datetime.now(timezone.utc) if entity is None else getattr(entity, "received_at", None),
    )
    if isinstance(received_at, datetime) and received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    responsible_raw = field(
        "responsible_id",
        form.responsible_id.data or "",
        default=str(entity.responsible_id) if entity and entity.responsible_id else "",
    )
    responsible_id = _uuid_or_none(str(responsible_raw) if responsible_raw else "")

    return RequestPayload(
        number=field("number", form.number.data, default=RequestRepository.next_number()),
        title=address.strip()[:500] or "Без адреса",
        description=field("description", form.description.data, default=""),
        address=address,
        pp=field("pp", form.pp.data, default=None),
        received_at=received_at,
        dispatcher_name=field("dispatcher_name", form.dispatcher_name.data, default=None),
        latitude=field("latitude", form.latitude.data, default=None),
        longitude=field("longitude", form.longitude.data, default=None),
        phone=field("phone", form.phone.data, default=None),
        applicant_name=field("applicant_name", form.applicant_name.data, default="—"),
        priority=field("priority", form.priority.data, default=Priority.MEDIUM.value),
        status_id=status_id,
        responsible_id=responsible_id,
        executor_id=_resolve_uuid_field("executor_id", form.executor_id.data or "", entity),
    )


def _prepare_filter_form(form: RequestFilterForm) -> None:
    statuses = RequestRepository.get_statuses()
    masters = RequestRepository.get_masters()
    dispatchers = RequestRepository.get_dispatchers()
    users = RequestRepository.get_users()

    form.status_id.choices = [("", "Все статусы")] + [
        (str(item.id), item.name) for item in statuses
    ]
    form.responsible_id.choices = [("", "Любой")] + [
        (str(item.id), item.full_name) for item in masters
    ]
    form.dispatcher_name.choices = [("", "Любой")] + [(d.name, d.name) for d in dispatchers]
    form.executor_id.choices = [("", "Любой")] + [(str(item.id), item.full_name) for item in users]


def _prepare_request_form(form: RequestForm) -> None:
    from app.core.builtin_field_service import BuiltinFieldService

    statuses = RequestRepository.get_statuses()
    masters = RequestRepository.get_masters()
    dispatchers = RequestRepository.get_dispatchers()
    users = RequestRepository.get_users()

    form.status_id.choices = [(str(item.id), item.name) for item in statuses]
    form.responsible_id.choices = [("", "Не назначен")] + [
        (str(item.id), item.full_name) for item in masters
    ]
    form.dispatcher_name.choices = [("", "Выберите диспетчера")] + [
        (d.name, d.name) for d in dispatchers
    ]
    form.executor_id.choices = [("", "Не назначен")] + [
        (str(item.id), item.full_name) for item in users
    ]
    BuiltinFieldService.apply_to_form(form, "requests")


def _prepare_assign_master_form(form: AssignMasterForm) -> None:
    masters = RequestRepository.get_masters()
    form.master_id.choices = [("", "Выберите мастера")] + [
        (str(item.id), item.full_name) for item in masters
    ]


def _apply_request_create_defaults(form: RequestForm) -> None:
    from datetime import datetime, timezone

    if request.method != "GET":
        return
    form.number.data = RequestRepository.next_number()
    form.description.data = ""
    form.address.data = ""
    form.pp.data = ""
    form.applicant_name.data = ""
    form.priority.data = Priority.MEDIUM.value
    form.received_at.data = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    status = RequestRepository.get_status_by_code(STATUS_NEW)
    if status is not None:
        form.status_id.data = str(status.id)
    form.responsible_id.data = ""
    form.dispatcher_name.data = ""


def _build_filters() -> RequestFilter:
    return RequestFilter(
        q=request.args.get("q", ""),
        status_id=request.args.get("status_id", ""),
        priority=request.args.get("priority", ""),
        responsible_id=request.args.get("responsible_id", ""),
        dispatcher_name=request.args.get("dispatcher_name", ""),
        executor_id=request.args.get("executor_id", ""),
        preset=request.args.get("preset", ""),
        sort_by=request.args.get("sort_by", "received_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )


def _workflow_redirect(req, message: str, category: str = "success"):
    flash(message, category)
    return redirect(url_for("requests.detail", request_id=req.id))


@requests_bp.route("/")
@login_required
@permission_required(PERM_REQUESTS_VIEW)
def index():
    filter_form = RequestFilterForm(request.args)
    _prepare_filter_form(filter_form)

    filters = _build_filters()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = RequestRepository.paginated_list(
        filters,
        page=page,
        per_page=per_page,
        current_user_id=current_user.id,
    )

    return render_template(
        "requests/index.html",
        filter_form=filter_form,
        requests_pagination=pagination,
        filters=filters,
    )


@requests_bp.route("/table")
@login_required
@permission_required(PERM_REQUESTS_VIEW)
def table():
    filters = _build_filters()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = RequestRepository.paginated_list(
        filters,
        page=page,
        per_page=per_page,
        current_user_id=current_user.id,
    )
    html = render_template(
        "requests/partials/table.html",
        requests_pagination=pagination,
    )
    pager = render_template(
        "requests/partials/pagination.html",
        requests_pagination=pagination,
    )
    return jsonify({"table_html": html, "pagination_html": pager})


_CF = "requests"


def _cf_form(entity_id=None):
    return custom_field_form_context(_CF, entity_id)


@requests_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_REQUESTS_CREATE)
def create():
    form = RequestForm()
    _prepare_request_form(form)
    _apply_request_create_defaults(form)

    if form.validate_on_submit():
        try:
            payload = _request_payload_from_form(form)
            created = RequestService.create_request(payload, current_user.id)
            save_custom_fields(_CF, created.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Заявка успешно создана.", id=str(created.id))
            flash("Заявка успешно создана.", "success")
            return redirect(url_for("requests.detail", request_id=created.id))
        except (ValidationError, ValueError) as exc:
            if is_ajax():
                html = render_template(
                    "requests/partials/form_modal.html",
                    form=form,
                    form_action=url_for("requests.create"),
                    **_cf_form(),
                )
                return ajax_error(str(exc), html=html)
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        html = render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.create"),
            **_cf_form(),
        )
        return ajax_error(form_errors_message(form), html=html)

    if is_ajax():
        return render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.create"),
            **_cf_form(),
        )
    return render_template("requests/form.html", form=form, mode="create")


@requests_bp.route("/<uuid:request_id>")
@login_required
@permission_required(PERM_REQUESTS_VIEW)
def detail(request_id: uuid.UUID):
    req = RequestRepository.get_by_id(request_id)
    if req is None:
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))

    comments = list(
        Comment.query.filter_by(
            entity_type="request",
            entity_id=req.id,
            deleted_at=None,
        )
        .order_by(Comment.created_at.desc())
        .all()
    )
    attachments = list(
        Attachment.query.filter_by(
            entity_type="request",
            entity_id=req.id,
            deleted_at=None,
        )
        .order_by(Attachment.created_at.desc())
        .all()
    )
    comment_form = RequestCommentForm()
    material_form = RequestMaterialForm()
    attachment_form = RequestAttachmentForm()
    assign_form = AssignMasterForm()
    _prepare_assign_master_form(assign_form)
    actions = available_actions(req, current_user)
    dispatcher = db.session.get(User, req.created_by) if req.created_by else None
    lifecycle = lifecycle_progress(req.status.code if req.status else None)

    photos = [f for f in attachments if (f.mime_type or "").startswith("image/")]
    documents = [f for f in attachments if not (f.mime_type or "").startswith("image/")]
    can_edit_files = current_user.has_permission(PERM_REQUESTS_EDIT)
    file_items = [
        {
            "name": f.file_name,
            "mime": f.mime_type,
            "preview_url": url_for(
                "requests.download_attachment",
                request_id=req.id,
                attachment_id=f.id,
                inline=1,
            ),
            "download_url": url_for(
                "requests.download_attachment",
                request_id=req.id,
                attachment_id=f.id,
            ),
            "delete_url": url_for(
                "requests.delete_attachment",
                request_id=req.id,
                attachment_id=f.id,
            ),
            "can_delete": can_edit_files,
            "created_at": f.created_at.strftime("%d.%m.%Y %H:%M"),
        }
        for f in attachments
    ]

    if is_ajax() and not request.args.get("full"):
        return render_template(
            "requests/partials/detail_modal.html",
            req=req,
            comments=comments,
            attachments=attachments,
            photos=photos,
            documents=documents,
            file_items=file_items,
            actions=actions,
            dispatcher=dispatcher,
            lifecycle=lifecycle,
            **custom_field_detail_context(_CF, req.id, current_user),
        )

    return render_template(
        "requests/detail.html",
        req=req,
        comments=comments,
        attachments=attachments,
        photos=photos,
        documents=documents,
        file_items=file_items,
        comment_form=comment_form,
        material_form=material_form,
        attachment_form=attachment_form,
        assign_form=assign_form,
        actions=actions,
        dispatcher=dispatcher,
        lifecycle=lifecycle,
    )


@requests_bp.route("/<uuid:request_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_REQUESTS_EDIT)
def edit(request_id: uuid.UUID):
    req = RequestRepository.get_by_id(request_id)
    if req is None:
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))

    form = RequestForm(obj=req)
    _prepare_request_form(form)
    if request.method == "GET":
        form.status_id.data = str(req.status_id)
        form.responsible_id.data = str(req.responsible_id) if req.responsible_id else ""
        form.executor_id.data = str(req.executor_id) if req.executor_id else ""
        form.dispatcher_name.data = req.dispatcher_name or ""
        form.pp.data = req.pp or ""
        if req.received_at is not None:
            form.received_at.data = req.received_at

    if form.validate_on_submit():
        try:
            payload = _request_payload_from_form(form, req)
            RequestService.update_request(req, payload, current_user.id)
            save_custom_fields(_CF, req.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Заявка обновлена.", id=str(req.id))
            flash("Заявка обновлена.", "success")
            return redirect(url_for("requests.detail", request_id=req.id))
        except (ValidationError, ValueError) as exc:
            if is_ajax():
                html = render_template(
                    "requests/partials/form_modal.html",
                    form=form,
                    form_action=url_for("requests.edit", request_id=req.id),
                    **_cf_form(req.id),
                )
                return ajax_error(str(exc), html=html)
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        html = render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.edit", request_id=req.id),
            **_cf_form(req.id),
        )
        return ajax_error(form_errors_message(form), html=html)

    if is_ajax():
        return render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.edit", request_id=req.id),
            **_cf_form(req.id),
        )
    return render_template("requests/form.html", form=form, mode="edit", req=req)


@requests_bp.route("/<uuid:request_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_DELETE)
def delete(request_id: uuid.UUID):
    req = RequestRepository.get_by_id(request_id)
    if req is None:
        return ajax_error("Заявка не найдена.", status=404)
    try:
        RequestService.delete_request(req, current_user.id)
        return ajax_ok("Заявка удалена.")
    except ValidationError as exc:
        return ajax_error(str(exc))


@requests_bp.route("/<uuid:request_id>/emergency-departed", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_DISPATCH)
def mark_emergency_departed(request_id: uuid.UUID):
    try:
        req = RequestService.mark_emergency_departed(request_id, current_user.id)
        return _workflow_redirect(req, "Статус: выехала аварийная бригада.")
    except (ValidationError, NotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("requests.detail", request_id=request_id))


@requests_bp.route("/<uuid:request_id>/assign-master", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_DISPATCH)
def assign_master(request_id: uuid.UUID):
    form = AssignMasterForm()
    _prepare_assign_master_form(form)
    if not form.validate_on_submit():
        flash(form_errors_message(form) or "Выберите мастера.", "danger")
        return redirect(url_for("requests.detail", request_id=request_id))
    master_id = _uuid_or_none(form.master_id.data or "")
    if master_id is None:
        flash("Выберите мастера.", "danger")
        return redirect(url_for("requests.detail", request_id=request_id))
    try:
        req = RequestService.assign_master(request_id, master_id, current_user.id)
        return _workflow_redirect(req, "Заявка передана мастеру.")
    except (ValidationError, NotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("requests.detail", request_id=request_id))


@requests_bp.route("/<uuid:request_id>/accept", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_APPROVE)
def accept_request(request_id: uuid.UUID):
    try:
        req = RequestService.accept_by_master(request_id, current_user.id)
        return _workflow_redirect(req, "Вы приняли заявку.")
    except (ValidationError, NotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("requests.detail", request_id=request_id))


@requests_bp.route("/<uuid:request_id>/start-work", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_APPROVE)
def start_work(request_id: uuid.UUID):
    try:
        req = RequestService.start_work(request_id, current_user.id)
        return _workflow_redirect(req, "Заявка в работе.")
    except (ValidationError, NotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("requests.detail", request_id=request_id))


@requests_bp.route("/<uuid:request_id>/complete", methods=["POST"])
@login_required
@any_permission_required(PERM_REQUESTS_EDIT, PERM_REQUESTS_APPROVE)
def complete_request(request_id: uuid.UUID):
    try:
        req = RequestService.complete_request(request_id, current_user.id)
        return _workflow_redirect(req, "Заявка завершена.")
    except (ValidationError, NotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("requests.detail", request_id=request_id))


@requests_bp.route("/<uuid:request_id>/cancel", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_DISPATCH)
def cancel_request(request_id: uuid.UUID):
    try:
        req = RequestService.cancel_request(request_id, current_user.id)
        return _workflow_redirect(req, "Заявка отменена.", "warning")
    except (ValidationError, NotFoundError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("requests.detail", request_id=request_id))


@requests_bp.route("/<uuid:request_id>/comment", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_EDIT)
def add_comment(request_id: uuid.UUID):
    req = RequestRepository.get_by_id(request_id)
    if req is None:
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))

    form = RequestCommentForm()
    if form.validate_on_submit():
        try:
            RequestService.add_comment(req, form.body.data, current_user.id)
            flash("Комментарий добавлен.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("requests.detail", request_id=req.id))


@requests_bp.route("/<uuid:request_id>/material", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_EDIT)
def add_material(request_id: uuid.UUID):
    req = RequestRepository.get_by_id(request_id)
    if req is None:
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))

    form = RequestMaterialForm()
    if form.validate_on_submit():
        try:
            RequestService.add_material(
                req,
                name=form.name.data,
                unit=form.unit.data,
                quantity=form.quantity.data,
                price=form.price.data,
                notes=form.notes.data,
                user_id=current_user.id,
            )
            flash("Материал добавлен.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    else:
        flash("Проверьте корректность данных материала.", "danger")
    return redirect(url_for("requests.detail", request_id=req.id))


@requests_bp.route("/<uuid:request_id>/attachment", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_EDIT)
def add_attachment(request_id: uuid.UUID):
    from app.core.upload_utils import collect_upload_files

    req = RequestRepository.get_by_id(request_id)
    if req is None:
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))

    form = RequestAttachmentForm()
    files = collect_upload_files(form.files.data, request.files.getlist("files"))
    if form.validate_on_submit() or files:
        try:
            if not files:
                raise ValidationError("Выберите хотя бы один файл.")
            created = RequestService.add_attachments(
                req,
                file_storages=files,
                user_id=current_user.id,
            )
            flash(f"Загружено файлов: {len(created)}.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    else:
        flash("Выберите файлы для загрузки.", "danger")
    return redirect(url_for("requests.detail", request_id=req.id, full=1))


@requests_bp.route("/<uuid:request_id>/attachment/<uuid:attachment_id>/download")
@login_required
@permission_required(PERM_REQUESTS_VIEW)
def download_attachment(request_id: uuid.UUID, attachment_id: uuid.UUID):
    req = RequestRepository.get_by_id(request_id)
    if req is None:
        abort(404)
    attachment = Attachment.query.filter_by(
        id=attachment_id,
        entity_type="request",
        entity_id=req.id,
        deleted_at=None,
    ).first()
    if attachment is None or not attachment.storage_key:
        abort(404)

    path = Path(current_app.config["UPLOAD_FOLDER"]) / attachment.storage_key
    if not path.is_file():
        abort(404)

    download_name = resolve_download_filename(
        attachment.file_name,
        storage_key=attachment.storage_key,
        mime_type=attachment.mime_type,
    )
    inline = request.args.get("inline") == "1"
    return send_file(
        path,
        mimetype=attachment.mime_type or "application/octet-stream",
        as_attachment=not inline,
        download_name=download_name,
    )


@requests_bp.route("/<uuid:request_id>/attachment/<uuid:attachment_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_EDIT)
def delete_attachment(request_id: uuid.UUID, attachment_id: uuid.UUID):
    req = RequestRepository.get_by_id(request_id)
    if req is None:
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))
    try:
        RequestService.delete_attachment(req, attachment_id, current_user.id)
        flash("Файл удалён.", "success")
    except (ValidationError, NotFoundError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("requests.detail", request_id=req.id))
