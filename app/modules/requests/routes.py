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
    DispatcherForm,
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
    from decimal import Decimal, InvalidOperation

    from app.core.address import load_address_selection_token
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
    signed_address = load_address_selection_token(form.address_selection_token.data)
    signed_normalized = str(
        (signed_address or {}).get("normalized_address") or ""
    ).strip()
    signed_selection_is_current = bool(signed_normalized) and address.strip() in {
        signed_normalized,
        signed_normalized[:500],
    }
    received_at = field(
        "received_at",
        form.received_at.data,
        default=datetime.now(timezone.utc) if entity is None else getattr(entity, "received_at", None),
    )
    if isinstance(received_at, datetime) and received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    def preserved(code, submitted, attr, default=None):
        """Скрытые builtin-поля не затираем при сохранении."""
        if entity is not None and not BFS.is_visible(m, code):
            return getattr(entity, attr, default)
        return field(code, submitted, default=default)

    def machine_field(code, default=None):
        """Служебные поля берём только из подписанной сервером подсказки."""
        if entity is not None and not FieldPermissionService.can_edit_field(u, m, "address"):
            return getattr(entity, code, default)
        if signed_selection_is_current:
            return signed_address.get(code, default)
        if entity is not None and address.strip() == (entity.address or "").strip():
            return getattr(entity, code, default)
        return default

    def signed_coordinate(code):
        value = machine_field(code)
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    if FieldPermissionService.can_edit_field(u, m, "district"):
        district = field("district", form.district.data, default=None)
    else:
        district = machine_field("district")

    responsible_raw = preserved(
        "responsible_id",
        form.responsible_id.data or "",
        "responsible_id",
        default=str(entity.responsible_id) if entity and entity.responsible_id else "",
    )
    if isinstance(responsible_raw, uuid.UUID):
        responsible_id = responsible_raw
    else:
        responsible_id = _uuid_or_none(str(responsible_raw) if responsible_raw else "")

    executor_raw = preserved(
        "executor_id",
        form.executor_id.data or "",
        "executor_id",
        default=str(entity.executor_id) if entity and entity.executor_id else "",
    )
    if isinstance(executor_raw, uuid.UUID):
        executor_id = executor_raw
    else:
        executor_id = _uuid_or_none(str(executor_raw) if executor_raw else "")

    return RequestPayload(
        number=field("number", form.number.data, default=RequestRepository.next_number()),
        title=address.strip()[:500] or "Без адреса",
        description=field("description", form.description.data, default=""),
        address=address,
        original_address=machine_field("original_address", default=address),
        normalized_address=machine_field("normalized_address"),
        region=machine_field("region"),
        district=district,
        settlement=machine_field("settlement"),
        street=machine_field("street"),
        house=machine_field("house"),
        address_source=machine_field("address_source"),
        address_external_id=machine_field("address_external_id"),
        pp=field("pp", form.pp.data, default=None),
        received_at=received_at,
        dispatcher_name=field("dispatcher_name", form.dispatcher_name.data, default=None),
        latitude=signed_coordinate("latitude"),
        longitude=signed_coordinate("longitude"),
        phone=field("phone", form.phone.data, default=None),
        applicant_name=field("applicant_name", form.applicant_name.data, default="—"),
        priority=field("priority", form.priority.data, default=Priority.MEDIUM.value),
        status_id=status_id,
        responsible_id=responsible_id,
        executor_id=executor_id,
        has_barrier=bool(field("has_barrier", form.has_barrier.data, default=False)),
        barrier_phone=field("barrier_phone", form.barrier_phone.data, default=None),
    )


def _prepare_filter_form(form: RequestFilterForm) -> None:
    statuses = RequestRepository.get_statuses()
    dispatchers = RequestRepository.get_dispatchers()

    form.status_id.choices = [("", "Все статусы")] + [
        (str(item.id), item.name) for item in statuses
    ]
    form.dispatcher_name.choices = [("", "Любой")] + [(d.name, d.name) for d in dispatchers]


def _prepare_request_form(form: RequestForm) -> None:
    from app.core.builtin_field_service import BuiltinFieldService

    statuses = RequestRepository.get_statuses()
    masters = RequestRepository.get_masters()
    dispatchers = RequestRepository.get_dispatchers()

    form.status_id.choices = [(str(item.id), item.name) for item in statuses]
    form.responsible_id.choices = [("", "Не назначен")] + [
        (str(item.id), item.full_name) for item in masters
    ]
    form.dispatcher_name.choices = [("", "Выберите диспетчера")] + [
        (d.name, d.name) for d in dispatchers
    ]
    form.executor_id.choices = [("", "Не назначен")]
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
    form.original_address.data = ""
    form.normalized_address.data = ""
    form.region.data = ""
    form.district.data = ""
    form.settlement.data = ""
    form.street.data = ""
    form.house.data = ""
    form.address_source.data = ""
    form.address_external_id.data = ""
    form.address_selection_token.data = ""
    form.latitude.data = None
    form.longitude.data = None
    form.pp.data = ""
    form.applicant_name.data = ""
    form.priority.data = Priority.MEDIUM.value
    form.received_at.data = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    status = RequestRepository.get_status_by_code(STATUS_NEW)
    if status is not None:
        form.status_id.data = str(status.id)
    form.responsible_id.data = ""
    form.dispatcher_name.data = ""
    form.has_barrier.data = False
    form.barrier_phone.data = ""


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
    return render_template(
        "requests/index.html",
        filter_form=filter_form,
        filters=_build_filters(),
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


@requests_bp.route("/dispatchers", methods=["GET", "POST"])
@login_required
@any_permission_required(PERM_REQUESTS_DISPATCH, PERM_REQUESTS_EDIT)
def dispatchers():
    form = DispatcherForm()
    if form.validate_on_submit():
        try:
            RequestRepository.create_dispatcher(
                name=form.name.data or "",
                sort_order=int(form.sort_order.data or 0),
                is_active=bool(form.is_active.data),
                user_id=current_user.id,
            )
            flash("Диспетчер добавлен.", "success")
            return redirect(url_for("requests.dispatchers"))
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Не удалось добавить: {exc}", "danger")
    items = RequestRepository.list_dispatchers_all()
    return render_template(
        "requests/dispatchers.html",
        form=form,
        items=items,
    )


@requests_bp.route("/dispatchers/<uuid:dispatcher_id>/edit", methods=["GET", "POST"])
@login_required
@any_permission_required(PERM_REQUESTS_DISPATCH, PERM_REQUESTS_EDIT)
def edit_dispatcher(dispatcher_id: uuid.UUID):
    item = RequestRepository.get_dispatcher(dispatcher_id)
    if item is None:
        flash("Диспетчер не найден.", "danger")
        return redirect(url_for("requests.dispatchers"))
    form = DispatcherForm()
    if request.method == "GET":
        form.name.data = item.name
        form.sort_order.data = item.sort_order
        form.is_active.data = item.is_active
    if form.validate_on_submit():
        RequestRepository.update_dispatcher(
            item,
            name=form.name.data or "",
            sort_order=int(form.sort_order.data or 0),
            is_active=bool(form.is_active.data),
            user_id=current_user.id,
        )
        flash("Диспетчер сохранён.", "success")
        return redirect(url_for("requests.dispatchers"))
    return render_template(
        "requests/dispatcher_form.html",
        form=form,
        item=item,
    )


@requests_bp.route("/dispatchers/<uuid:dispatcher_id>/delete", methods=["POST"])
@login_required
@any_permission_required(PERM_REQUESTS_DISPATCH, PERM_REQUESTS_EDIT)
def delete_dispatcher(dispatcher_id: uuid.UUID):
    item = RequestRepository.get_dispatcher(dispatcher_id)
    if item is None:
        flash("Диспетчер не найден.", "danger")
        return redirect(url_for("requests.dispatchers"))
    RequestRepository.delete_dispatcher(item, current_user.id)
    flash("Диспетчер удалён.", "success")
    return redirect(url_for("requests.dispatchers"))


@requests_bp.route("/api/format-address")
@login_required
@any_permission_required(PERM_REQUESTS_CREATE, PERM_REQUESTS_EDIT, PERM_REQUESTS_VIEW)
def format_address_api():
    from app.modules.requests.address_format import format_address

    raw = request.args.get("address") or ""
    formatted = format_address(raw)
    return jsonify({"address": formatted, "raw": raw})


@requests_bp.route("/api/address-suggestions")
@login_required
@any_permission_required(PERM_REQUESTS_CREATE, PERM_REQUESTS_EDIT, PERM_REQUESTS_VIEW)
def address_suggestions():
    from app.core.address import (
        get_address_suggestion_service,
        make_address_selection_token,
    )

    query = (request.args.get("q") or "").strip()
    if len(query) < 3:
        return jsonify({"suggestions": []})
    limit = int(current_app.config.get("ADDRESS_SUGGESTION_LIMIT", 8))
    suggestions = get_address_suggestion_service().suggest(query, limit=limit)
    payload = []
    for item in suggestions:
        data = item.as_dict()
        data["selection_token"] = make_address_selection_token(item)
        payload.append(data)
    return jsonify({"suggestions": payload})


@requests_bp.route("/api/open-by-address")
@login_required
@any_permission_required(PERM_REQUESTS_CREATE, PERM_REQUESTS_EDIT, PERM_REQUESTS_VIEW)
def open_by_address():
    address = (request.args.get("address") or "").strip()
    exclude_raw = request.args.get("exclude_id") or ""
    exclude_id = _uuid_or_none(exclude_raw)
    if len(address) < 3:
        return jsonify({"found": False})

    existing = RequestRepository.find_open_by_address(address, exclude_id=exclude_id)
    if existing is None:
        return jsonify({"found": False})

    received = None
    if existing.received_at:
        received = existing.received_at.strftime("%d.%m.%Y %H:%M")
    return jsonify(
        {
            "found": True,
            "id": str(existing.id),
            "number": existing.number,
            "address": existing.address,
            "status": existing.status.name if existing.status else None,
            "received_at": received,
            "repeat_count": int(existing.repeat_count or 0),
            "url": url_for("requests.detail", request_id=existing.id),
        }
    )


@requests_bp.route("/<uuid:request_id>/mark-repeat", methods=["POST"])
@login_required
@permission_required(PERM_REQUESTS_EDIT)
def mark_repeat(request_id: uuid.UUID):
    from datetime import datetime, timezone

    req = RequestRepository.get_by_id(request_id)
    if req is None:
        if is_ajax():
            return ajax_error("Заявка не найдена.", status=404)
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))

    payload = request.json if request.is_json else request.form
    call_raw = payload.get("received_at") if payload else None
    call_at = None
    if call_raw:
        try:
            call_at = datetime.fromisoformat(str(call_raw).replace("Z", "+00:00"))
        except ValueError:
            try:
                call_at = datetime.strptime(str(call_raw), "%Y-%m-%dT%H:%M").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                call_at = None

    has_barrier_raw = payload.get("has_barrier") if payload else None
    has_barrier = None
    if has_barrier_raw is not None:
        has_barrier = str(has_barrier_raw).lower() in ("1", "true", "on", "yes")

    try:
        updated = RequestService.mark_repeat_call(
            req,
            current_user.id,
            call_at=call_at,
            phone=payload.get("phone") if payload else None,
            applicant_name=payload.get("applicant_name") if payload else None,
            description=payload.get("description") if payload else None,
            has_barrier=has_barrier,
            barrier_phone=payload.get("barrier_phone") if payload else None,
        )
    except ValidationError as exc:
        if is_ajax():
            return ajax_error(str(exc))
        flash(str(exc), "danger")
        return redirect(url_for("requests.detail", request_id=req.id))

    detail_url = url_for("requests.detail", request_id=updated.id)
    if is_ajax():
        return ajax_ok(
            "Повторное обращение зафиксировано.",
            id=str(updated.id),
            redirect_url=detail_url,
            repeat_count=updated.repeat_count,
        )
    flash("Повторное обращение зафиксировано.", "success")
    return redirect(detail_url)


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
                    mode="create",
                    **_cf_form(),
                )
                return ajax_error(str(exc), html=html)
            flash(str(exc), "danger")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Не удалось создать заявку")
            message = "Не удалось сохранить заявку. Проверьте поля и повторите."
            if is_ajax():
                html = render_template(
                    "requests/partials/form_modal.html",
                    form=form,
                    form_action=url_for("requests.create"),
                    mode="create",
                    **_cf_form(),
                )
                return ajax_error(message, html=html)
            flash(message, "danger")
    elif is_ajax() and request.method == "POST":
        html = render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.create"),
            mode="create",
            **_cf_form(),
        )
        return ajax_error(form_errors_message(form), html=html)

    if is_ajax():
        return render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.create"),
            mode="create",
            **_cf_form(),
        )
    return render_template(
        "requests/form.html",
        form=form,
        mode="create",
        **_cf_form(),
    )


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
            comment_form=comment_form,
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
        **custom_field_detail_context(_CF, req.id, current_user),
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
        form.has_barrier.data = bool(req.has_barrier)
        form.barrier_phone.data = req.barrier_phone or ""
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
                    mode="edit",
                    req=req,
                    **_cf_form(req.id),
                )
                return ajax_error(str(exc), html=html)
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        html = render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.edit", request_id=req.id),
            mode="edit",
            req=req,
            **_cf_form(req.id),
        )
        return ajax_error(form_errors_message(form), html=html)

    if is_ajax():
        return render_template(
            "requests/partials/form_modal.html",
            form=form,
            form_action=url_for("requests.edit", request_id=req.id),
            mode="edit",
            req=req,
            **_cf_form(req.id),
        )
    return render_template(
        "requests/form.html",
        form=form,
        mode="edit",
        req=req,
        **_cf_form(req.id),
    )


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
        if is_ajax():
            return ajax_error("Заявка не найдена.", status=404)
        flash("Заявка не найдена.", "danger")
        return redirect(url_for("requests.index"))

    form = RequestCommentForm()
    if form.validate_on_submit():
        try:
            RequestService.add_comment(req, form.body.data, current_user.id)
            if is_ajax():
                return ajax_ok("Комментарий добавлен.")
            flash("Комментарий добавлен.", "success")
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc), status=422)
            flash(str(exc), "danger")
    elif is_ajax():
        return ajax_error(
            form_errors_message(form),
            errors=form.errors,
            status=422,
        )
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
