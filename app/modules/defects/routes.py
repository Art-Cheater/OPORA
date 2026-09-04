"""Маршруты дефектов."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.core.address import load_address_selection_token
from app.core.decorators import request_or_legacy_defect_permission_required
from app.core.exceptions import NotFoundError, ValidationError
from app.core.navigation import back_navigation
from app.core.field_permissions import FieldPermissionService
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.core.upload_utils import resolve_download_filename, resolve_storage_path
from app.extensions import db
from app.models.auth.constants import (
    PERM_DEFECTS_CREATE,
    PERM_DEFECTS_DELETE,
    PERM_DEFECTS_EDIT,
    PERM_DEFECTS_FILE_DELETE,
    PERM_DEFECTS_FILE_UPLOAD,
    PERM_DEFECTS_STATUS_CHANGE,
    PERM_DEFECTS_VIEW,
    PERM_REQUESTS_CREATE,
    PERM_REQUESTS_DELETE,
    PERM_REQUESTS_EDIT,
    PERM_REQUESTS_VIEW,
)
from app.models.communication.comment import Comment
from app.models.enums import EntityType
from app.models.files.attachment import Attachment
from app.modules.defects.blueprint import defects_bp
from app.modules.defects.forms import (
    DefectAttachmentForm,
    DefectCommentForm,
    DefectFilterForm,
    DefectForm,
    DefectStatusForm,
)
from app.modules.defects.repositories import DefectFilter, DefectRepository
from app.modules.defects.services import DefectPayload, DefectService
from app.modules.defects.workflow import ALLOWED_TRANSITIONS, can_transition
from app.modules.requests.districts import normalize_request_district
from app.modules.requests.repositories import RequestRepository
from app.modules.requests.services import RequestService


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _payload_from_form(form: DefectForm, entity=None) -> DefectPayload:
    fp = FieldPermissionService.resolve_field
    u, m = current_user, "defects"

    def field(code, submitted, default=None):
        raw = fp(u, m, code, submitted, entity)
        return default if raw is None and entity is None else raw

    address = field("address", form.address.data, default="") or ""
    signed = load_address_selection_token(form.address_selection_token.data)
    signed_normalized = str((signed or {}).get("normalized_address") or "").strip()
    signed_ok = bool(signed_normalized) and address.strip() in {signed_normalized, signed_normalized[:500]}

    def machine(code, default=None):
        if entity is not None and not FieldPermissionService.can_edit_field(u, m, "address"):
            return getattr(entity, code, default)
        if signed_ok:
            return signed.get(code, default)
        if entity is not None and address.strip() == (entity.address or "").strip():
            return getattr(entity, code, default)
        return default

    def coord(code):
        value = machine(code)
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    return DefectPayload(
        number=field("number", form.number.data, default=DefectRepository.next_number()) or DefectRepository.next_number(),
        description=field("description", form.description.data, default="") or "",
        category_id=_uuid_or_none(str(field("category_id", form.category_id.data, default="") or "")),
        address=address,
        original_address=machine("original_address", default=address),
        normalized_address=machine("normalized_address"),
        region=machine("region"),
        district=normalize_request_district(field("district", form.district.data, default=None)),
        settlement=machine("settlement"),
        street=machine("street"),
        house=machine("house"),
        address_source=machine("address_source"),
        address_external_id=machine("address_external_id"),
        latitude=coord("latitude"),
        longitude=coord("longitude"),
        responsible_id=_uuid_or_none(str(field("responsible_id", form.responsible_id.data, default="") or "")),
        pp=(field("pp", form.pp.data, default="") or "").strip() or None,
    )


def _prepare_form(form: DefectForm) -> None:
    form.category_id.choices = [(str(c.id), c.name) for c in DefectRepository.get_categories()]
    form.responsible_id.choices = [("", "Не назначен")] + [
        (str(u.id), u.full_name) for u in DefectRepository.get_masters()
    ]
    form.status_code.choices = [(s.code, s.name) for s in DefectRepository.get_statuses()]


def _prepare_filter(form: DefectFilterForm) -> None:
    form.status_id.choices = [("", "Все статусы")] + [(str(s.id), s.name) for s in DefectRepository.get_statuses()]
    form.category_id.choices = [("", "Все категории")] + [(str(c.id), c.name) for c in DefectRepository.get_categories()]


@defects_bp.route("/")
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_VIEW, PERM_DEFECTS_VIEW)
def index():
    filter_form = DefectFilterForm(request.args)
    _prepare_filter(filter_form)
    return render_template(
        "defects/index.html",
        filter_form=filter_form,
        journals=RequestRepository.get_journals(),
        tab="defects",
    )


@defects_bp.route("/table")
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_VIEW, PERM_DEFECTS_VIEW)
def table():
    filters = DefectFilter(
        q=request.args.get("q", ""),
        number=request.args.get("number", ""),
        district=request.args.get("district", ""),
        status_id=request.args.get("status_id", ""),
        category_id=request.args.get("category_id", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    per_page = request.args.get("per_page", 10, type=int)
    if per_page not in {10, 25, 50, 100}:
        per_page = 10
    pagination = DefectRepository.paginated_list(
        filters,
        page=request.args.get("page", 1, type=int),
        per_page=per_page,
    )
    return jsonify(
        {
            "entity": "defect",
            "table_html": render_template("defects/partials/table.html", pagination=pagination),
            "pagination_html": render_template("defects/partials/pagination.html", pagination=pagination),
        }
    )


@defects_bp.route("/map.json")
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_VIEW, PERM_DEFECTS_VIEW)
def map_json():
    return jsonify({"points": DefectRepository.map_points(), "remaining": 0})


@defects_bp.route("/new", methods=["GET", "POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_CREATE, PERM_DEFECTS_CREATE)
def create():
    form = DefectForm()
    _prepare_form(form)
    if request.method == "GET":
        form.number.data = DefectRepository.next_number()
    if form.validate_on_submit():
        try:
            item = DefectService.create(_payload_from_form(form), current_user.id)
            if is_ajax():
                return ajax_ok("Дефект создан.", id=str(item.id), redirect=url_for("defects.detail", defect_id=item.id))
            flash("Дефект создан.", "success")
            return redirect(url_for("defects.detail", defect_id=item.id))
        except ValidationError as exc:
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(form_errors_message(form), html=render_template(
            "defects/partials/form_modal.html", form=form, form_action=url_for("defects.create"), mode="create"
        ))
    if is_ajax():
        return render_template("defects/partials/form_modal.html", form=form, form_action=url_for("defects.create"), mode="create")
    return render_template("defects/form.html", form=form, mode="create")


@defects_bp.route("/<uuid:defect_id>")
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_VIEW, PERM_DEFECTS_VIEW)
def detail(defect_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    if item is None:
        flash("Дефект не найден.", "danger")
        return redirect(url_for("defects.index"))
    comments = list(
        Comment.query.filter_by(entity_type=EntityType.DEFECT.value, entity_id=item.id, deleted_at=None)
        .order_by(Comment.created_at.desc())
        .all()
    )
    attachments = list(
        Attachment.query.filter_by(entity_type=EntityType.DEFECT.value, entity_id=item.id, deleted_at=None)
        .order_by(Attachment.created_at.desc())
        .all()
    )
    status_form = DefectStatusForm()
    current_code = item.status.code if item.status else ""
    status_form.status_code.choices = [
        (s.code, s.name)
        for s in DefectRepository.get_statuses()
        if can_transition(current_code, s.code)
    ]
    history = list(item.history)[:50]
    back_url, back_label = back_navigation(fallback="/requests/?tab=defects")
    return render_template(
        "defects/detail.html",
        item=item,
        comments=comments,
        attachments=attachments,
        comment_form=DefectCommentForm(),
        attachment_form=DefectAttachmentForm(),
        status_form=status_form,
        history=history,
        back_url=back_url,
        back_label=back_label,
    )


@defects_bp.route("/<uuid:defect_id>/edit", methods=["GET", "POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_EDIT, PERM_DEFECTS_EDIT)
def edit(defect_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    if item is None:
        flash("Дефект не найден.", "danger")
        return redirect(url_for("defects.index"))
    form = DefectForm(obj=item)
    _prepare_form(form)
    if request.method == "GET":
        form.category_id.data = str(item.category_id)
        form.responsible_id.data = str(item.responsible_id) if item.responsible_id else ""
        form.district.data = normalize_request_district(item.district) or ""
        form.status_code.data = item.status.code if item.status else ""
    if form.validate_on_submit():
        try:
            previous_status = item.status.code if item.status else ""
            DefectService.update(item, _payload_from_form(form, item), current_user.id)
            requested_status = (form.status_code.data or "").strip()
            if (
                requested_status
                and requested_status != previous_status
                and current_user.has_any_permission(PERM_REQUESTS_EDIT, PERM_DEFECTS_STATUS_CHANGE)
                and current_user.can_edit_field("defects", "status_id")
            ):
                DefectService.change_status(
                    item,
                    requested_status,
                    current_user.id,
                    comment="Статус изменён при редактировании дефекта",
                    enforce_transition=False,
                )
            flash("Дефект обновлён.", "success")
            return redirect(url_for("defects.detail", defect_id=item.id))
        except ValidationError as exc:
            flash(str(exc), "danger")
    if is_ajax():
        return render_template(
            "defects/partials/form_modal.html",
            form=form,
            form_action=url_for("defects.edit", defect_id=item.id),
            mode="edit",
        )
    return render_template("defects/form.html", form=form, mode="edit", item=item)


@defects_bp.route("/<uuid:defect_id>/delete", methods=["POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_DELETE, PERM_DEFECTS_DELETE)
def delete(defect_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    if item is None:
        flash("Дефект не найден.", "danger")
        return redirect(url_for("defects.index"))
    DefectService.delete(item, current_user.id)
    flash("Дефект удалён.", "success")
    if is_ajax():
        return ajax_ok("Дефект удалён.")
    return redirect(url_for("defects.index"))


@defects_bp.route("/<uuid:defect_id>/status", methods=["POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_EDIT, PERM_DEFECTS_STATUS_CHANGE)
def change_status(defect_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    if item is None:
        flash("Дефект не найден.", "danger")
        return redirect(url_for("defects.index"))
    form = DefectStatusForm()
    form.status_code.choices = [(s.code, s.name) for s in DefectRepository.get_statuses()]
    payload = request.get_json(silent=True) or {}
    status_code = (form.status_code.data or payload.get("status_code") or request.form.get("status_code") or "").strip()
    comment = form.comment.data or payload.get("comment")
    if not status_code:
        if is_ajax():
            return ajax_error("Укажите статус.")
        flash("Укажите статус.", "danger")
        return redirect(url_for("defects.detail", defect_id=item.id))
    try:
        DefectService.change_status(item, status_code, current_user.id, comment)
        if is_ajax():
            return ajax_ok("Статус обновлён.")
        flash("Статус обновлён.", "success")
    except ValidationError as exc:
        if is_ajax():
            return ajax_error(str(exc))
        flash(str(exc), "danger")
    return redirect(url_for("defects.detail", defect_id=item.id))


@defects_bp.route("/<uuid:defect_id>/comment", methods=["POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_EDIT, PERM_DEFECTS_EDIT)
def add_comment(defect_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    if item is None:
        flash("Дефект не найден.", "danger")
        return redirect(url_for("defects.index"))
    form = DefectCommentForm()
    if form.validate_on_submit():
        DefectService.add_comment(item, form.body.data or "", current_user.id)
        flash("Комментарий добавлен.", "success")
    return redirect(url_for("defects.detail", defect_id=item.id))


@defects_bp.route("/<uuid:defect_id>/attachment", methods=["POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_EDIT, PERM_DEFECTS_FILE_UPLOAD)
def add_attachment(defect_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    if item is None:
        flash("Дефект не найден.", "danger")
        return redirect(url_for("defects.index"))
    form = DefectAttachmentForm()
    if form.validate_on_submit():
        try:
            DefectService.add_attachments(item, request.files.getlist(form.files.name), current_user.id)
            flash("Файлы загружены.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("defects.detail", defect_id=item.id))


@defects_bp.route("/<uuid:defect_id>/attachment/<uuid:attachment_id>/download")
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_VIEW, PERM_DEFECTS_VIEW)
def download_attachment(defect_id: uuid.UUID, attachment_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    attachment = db.session.get(Attachment, attachment_id)
    if item is None or attachment is None or attachment.entity_id != item.id:
        flash("Файл не найден.", "danger")
        return redirect(url_for("defects.index"))
    path = resolve_storage_path(attachment.storage_key)
    return send_file(path, download_name=resolve_download_filename(attachment.file_name), as_attachment=request.args.get("inline") != "1")


@defects_bp.route("/<uuid:defect_id>/attachment/<uuid:attachment_id>/delete", methods=["POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_EDIT, PERM_DEFECTS_FILE_DELETE)
def delete_attachment(defect_id: uuid.UUID, attachment_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    attachment = db.session.get(Attachment, attachment_id)
    if item is None or attachment is None:
        flash("Файл не найден.", "danger")
        return redirect(url_for("defects.index"))
    try:
        DefectService.delete_attachment(item, attachment, current_user.id)
        flash("Файл удалён.", "success")
    except (NotFoundError, ValidationError) as exc:
        flash(str(exc), "danger")
    return redirect(url_for("defects.detail", defect_id=item.id))


@defects_bp.route("/<uuid:defect_id>/coords", methods=["GET", "POST"])
@login_required
@request_or_legacy_defect_permission_required(PERM_REQUESTS_VIEW, PERM_DEFECTS_VIEW)
def ensure_coords(defect_id: uuid.UUID):
    item = DefectRepository.get_by_id(defect_id)
    if item is None:
        return jsonify({"success": False, "message": "Не найден"}), 404
    if item.latitude is not None and item.longitude is not None:
        return jsonify({"success": True, "latitude": float(item.latitude), "longitude": float(item.longitude), "address": item.address})
    persist = current_user.has_any_permission(PERM_REQUESTS_EDIT, PERM_DEFECTS_EDIT)
    dummy = type("P", (), {})()
    dummy.address = item.address
    dummy.normalized_address = item.normalized_address
    dummy.original_address = item.original_address
    dummy.region = item.region
    dummy.district = item.district
    dummy.settlement = item.settlement
    dummy.street = item.street
    dummy.house = item.house
    dummy.address_source = item.address_source
    dummy.address_external_id = item.address_external_id
    dummy.latitude = item.latitude
    dummy.longitude = item.longitude
    RequestService._prepare_address(dummy)
    if dummy.latitude is None or dummy.longitude is None:
        return jsonify({"success": False, "message": "Не удалось определить координаты"})
    if persist:
        item.latitude = dummy.latitude
        item.longitude = dummy.longitude
        db.session.commit()
    return jsonify({"success": True, "latitude": float(dummy.latitude), "longitude": float(dummy.longitude), "address": item.address})
