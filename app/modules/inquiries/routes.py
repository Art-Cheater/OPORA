"""Маршруты обращений с корпоративной почты."""

from __future__ import annotations

import threading
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.auth.constants import (
    PERM_INQUIRIES_DELETE,
    PERM_INQUIRIES_EDIT,
    PERM_INQUIRIES_SYNC,
    PERM_INQUIRIES_VIEW,
)
from app.models.base import utcnow
from app.modules.inquiries.blueprint import inquiries_bp
from app.modules.inquiries.forms import InquiryFilterForm
from app.modules.inquiries.repositories import InquiryFilter, InquiryRepository
from app.modules.inquiries.services import InquiryService


@inquiries_bp.route("/")
@login_required
@permission_required(PERM_INQUIRIES_VIEW)
def index():
    form = InquiryFilterForm(request.args)
    pagination = InquiryRepository.paginated_list(
        InquiryFilter(q=request.args.get("q", ""), status=request.args.get("status", "")),
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 30, type=int),
    )
    return render_template(
        "inquiries/index.html",
        filter_form=form,
        pagination=pagination,
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        mailbox_state=InquiryService.mailbox_state(),
        configured=InquiryService.is_configured(),
        running=InquiryService.is_running(),
        mailbox=InquiryService.mailbox_config()["mailbox"],
        unread=InquiryRepository.unread_count(),
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
    flash("Забираем письма с kirovsvet@mail.ru. Обновите страницу через минуту.", "success")
    return redirect(url_for("inquiries.index"))


@inquiries_bp.route("/<uuid:inquiry_id>")
@login_required
@permission_required(PERM_INQUIRIES_VIEW)
def detail(inquiry_id):
    inquiry = InquiryRepository.get_by_id(inquiry_id)
    if inquiry is None:
        abort(404)
    if current_user.has_permission(PERM_INQUIRIES_EDIT):
        InquiryService.mark_seen(inquiry, current_user.id)
    files = InquiryService.attachments(inquiry.id)
    return render_template("inquiries/detail.html", inquiry=inquiry, files=files)


@inquiries_bp.route("/<uuid:inquiry_id>/status", methods=["POST"])
@login_required
@permission_required(PERM_INQUIRIES_EDIT)
def set_status(inquiry_id):
    inquiry = InquiryRepository.get_by_id(inquiry_id)
    if inquiry is None:
        abort(404)
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
    inquiry = InquiryRepository.get_by_id(inquiry_id)
    if inquiry is None:
        abort(404)
    item = next((file for file in InquiryService.attachments(inquiry.id) if file.id == file_id), None)
    if item is None:
        abort(404)
    path = Path(current_app.config["UPLOAD_FOLDER"]) / item.storage_key
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=item.file_name)


@inquiries_bp.route("/<uuid:inquiry_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_INQUIRIES_DELETE)
def delete(inquiry_id):
    inquiry = InquiryRepository.get_by_id(inquiry_id)
    if inquiry is None:
        abort(404)
    inquiry.deleted_at = utcnow()
    inquiry.updated_by = current_user.id
    db.session.commit()
    flash("Обращение скрыто.", "info")
    return redirect(url_for("inquiries.index"))
