"""Маршруты обращений с корпоративной почты."""

from __future__ import annotations

import threading
import uuid

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.upload_utils import resolve_download_filename
from app.extensions import db
from app.models.auth.constants import (
    PERM_INQUIRIES_DELETE,
    PERM_INQUIRIES_EDIT,
    PERM_INQUIRIES_SYNC,
    PERM_INQUIRIES_VIEW,
    PERM_MESSENGER_USE,
)
from app.models.base import utcnow
from app.modules.inquiries.access import can_access_inquiry, manages_mailbox
from app.modules.inquiries.blueprint import inquiries_bp
from app.modules.inquiries.forms import InquiryFilterForm
from app.modules.inquiries.repositories import InquiryFilter, InquiryRepository
from app.modules.inquiries.services import InquiryService


def _inquiry_filters() -> InquiryFilter:
    return InquiryFilter(q=request.args.get("q", ""), status=request.args.get("status", ""))


def _assigned_scope():
    if manages_mailbox(current_user):
        return None
    return current_user.id


def _get_visible_inquiry(inquiry_id):
    inquiry = InquiryRepository.get_by_id(inquiry_id)
    if inquiry is None or not can_access_inquiry(current_user, inquiry):
        abort(404)
    return inquiry


def _file_items(inquiry) -> list[dict]:
    items = []
    for file in InquiryService.attachments(inquiry.id):
        items.append(
            {
                "name": file.file_name,
                "mime": file.mime_type,
                "preview_url": url_for(
                    "inquiries.download",
                    inquiry_id=inquiry.id,
                    file_id=file.id,
                    inline=1,
                ),
                "download_url": url_for(
                    "inquiries.download",
                    inquiry_id=inquiry.id,
                    file_id=file.id,
                ),
                "created_at": file.created_at.strftime("%d.%m.%Y %H:%M") if file.created_at else "",
            }
        )
    return items


@inquiries_bp.route("/")
@login_required
@permission_required(PERM_INQUIRIES_VIEW)
def index():
    form = InquiryFilterForm(request.args)
    mailbox = manages_mailbox(current_user)
    return render_template(
        "inquiries/index.html",
        filter_form=form,
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        mailbox_state=InquiryService.mailbox_state() if mailbox else None,
        configured=InquiryService.is_configured() if mailbox else True,
        running=InquiryService.is_running() if mailbox else False,
        mailbox=InquiryService.mailbox_config()["mailbox"],
        unread=InquiryRepository.unread_count(assigned_to=_assigned_scope()),
        manages_mailbox=mailbox,
    )


@inquiries_bp.route("/table")
@login_required
@permission_required(PERM_INQUIRIES_VIEW)
def table():
    sees_all = manages_mailbox(current_user)
    pagination = InquiryRepository.paginated_list(
        _inquiry_filters(),
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 30, type=int),
        assigned_to=None if sees_all else current_user.id,
    )
    return jsonify(
        {
            "table_html": render_template(
                "inquiries/partials/table.html",
                pagination=pagination,
                sees_all=sees_all,
            ),
            "pagination_html": render_template("inquiries/partials/pagination.html", pagination=pagination),
        }
    )


@inquiries_bp.route("/sync", methods=["POST"])
@login_required
@permission_required(PERM_INQUIRIES_SYNC)
def sync_now():
    if not InquiryService.is_configured():
        flash("В .env не указан пароль ящика INQUIRY_IMAP_PASSWORD.", "danger")
        return redirect(url_for("inquiries.index"))
    if InquiryService.is_running():
        flash("Письма уже забираются. Обновите страницу через минуту.", "warning")
        return redirect(url_for("inquiries.index"))
    app = current_app._get_current_object()
    user_id = current_user.id

    def worker():
        with app.app_context():
            InquiryService.sync(user_id=user_id)

    threading.Thread(target=worker, daemon=True, name="inquiry-sync").start()
    flash("Забираем письма за 2026 год порциями. Старые не трогаем и с сайта уберём.", "success")
    return redirect(url_for("inquiries.index"))


@inquiries_bp.route("/<uuid:inquiry_id>")
@login_required
@permission_required(PERM_INQUIRIES_VIEW)
def detail(inquiry_id):
    inquiry = _get_visible_inquiry(inquiry_id)
    if inquiry.assigned_to == current_user.id:
        InquiryService.mark_seen(inquiry, current_user.id)
    elif inquiry.assigned_to is None and current_user.has_permission(PERM_INQUIRIES_EDIT):
        InquiryService.mark_seen(inquiry, current_user.id)
    files = InquiryService.attachments(inquiry.id)
    return render_template(
        "inquiries/detail.html",
        inquiry=inquiry,
        files=files,
        file_items=_file_items(inquiry),
        can_forward=current_user.has_permission(PERM_MESSENGER_USE),
    )


@inquiries_bp.route("/<uuid:inquiry_id>/forward", methods=["POST"])
@login_required
@permission_required(PERM_INQUIRIES_VIEW)
@permission_required(PERM_MESSENGER_USE)
def forward(inquiry_id):
    inquiry = _get_visible_inquiry(inquiry_id)
    payload = request.json if request.is_json else request.form
    raw_id = (payload or {}).get("user_id")
    try:
        to_user_id = uuid.UUID(str(raw_id))
    except (ValueError, TypeError, AttributeError):
        return jsonify({"error": "Выберите сотрудника."}), 400
    try:
        result = InquiryService.forward(inquiry, to_user_id=to_user_id, actor=current_user)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, **result})


@inquiries_bp.route("/<uuid:inquiry_id>/status", methods=["POST"])
@login_required
@permission_required(PERM_INQUIRIES_EDIT)
def set_status(inquiry_id):
    inquiry = _get_visible_inquiry(inquiry_id)
    status = (request.form.get("status") or "").strip()
    try:
        InquiryService.set_status(inquiry, status, current_user.id)
    except ValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("inquiries.detail", inquiry_id=inquiry.id))
    flash("Статус обновлён.", "success")
    return redirect(url_for("inquiries.detail", inquiry_id=inquiry.id))


@inquiries_bp.route("/<uuid:inquiry_id>/files/<uuid:file_id>")
@login_required
@permission_required(PERM_INQUIRIES_VIEW)
def download(inquiry_id, file_id):
    inquiry = _get_visible_inquiry(inquiry_id)
    item = next((file for file in InquiryService.attachments(inquiry.id) if file.id == file_id), None)
    if item is None:
        abort(404)
    path = InquiryService.ensure_attachment_file(inquiry, item)
    if path is None:
        abort(404)
    download_name = resolve_download_filename(
        item.file_name,
        storage_key=item.storage_key,
        mime_type=item.mime_type,
    )
    inline = request.args.get("inline") == "1"
    return send_file(
        path,
        mimetype=item.mime_type or "application/octet-stream",
        as_attachment=not inline,
        download_name=download_name,
    )


@inquiries_bp.route("/<uuid:inquiry_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_INQUIRIES_DELETE)
def delete(inquiry_id):
    inquiry = _get_visible_inquiry(inquiry_id)
    inquiry.deleted_at = utcnow()
    inquiry.updated_by = current_user.id
    db.session.commit()
    flash("Обращение скрыто.", "info")
    return redirect(url_for("inquiries.index"))
