"""Маршруты личных документов."""

from __future__ import annotations

import uuid

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.core.exceptions import NotFoundError, ValidationError
from app.core.upload_utils import collect_upload_files, resolve_download_filename
from app.modules.documents.blueprint import documents_bp
from app.modules.documents.forms import PersonalDocumentForm
from app.modules.documents.services import PersonalDocumentService


def _file_items(user_id: uuid.UUID) -> list[dict]:
    items = []
    for file in PersonalDocumentService.list_for(user_id):
        items.append(
            {
                "name": file.file_name,
                "mime": file.mime_type,
                "preview_url": url_for(
                    "documents.download",
                    file_id=file.id,
                    inline=1,
                ),
                "download_url": url_for("documents.download", file_id=file.id),
                "delete_url": url_for("documents.delete", file_id=file.id),
                "can_delete": True,
                "created_at": file.created_at.strftime("%d.%m.%Y %H:%M") if file.created_at else "",
            }
        )
    return items


@documents_bp.route("/")
@login_required
def index():
    form = PersonalDocumentForm()
    return render_template(
        "documents/index.html",
        form=form,
        file_items=_file_items(current_user.id),
    )


@documents_bp.route("/upload", methods=["POST"])
@login_required
def upload():
    form = PersonalDocumentForm()
    files = collect_upload_files(form.files.data, request.files.getlist("files"))
    if form.validate_on_submit() or files:
        try:
            if not files:
                raise ValidationError("Выберите хотя бы один файл.")
            saved = PersonalDocumentService.add_files(current_user.id, files)
            flash(f"Загружено файлов: {saved}.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    else:
        flash("Выберите хотя бы один файл.", "danger")
    return redirect(url_for("documents.index"))


@documents_bp.route("/<uuid:file_id>")
@login_required
def download(file_id: uuid.UUID):
    item = PersonalDocumentService.get_own(current_user.id, file_id)
    if item is None:
        abort(404)
    path = PersonalDocumentService.disk_path(item)
    if not path.is_file():
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


@documents_bp.route("/<uuid:file_id>/delete", methods=["POST"])
@login_required
def delete(file_id: uuid.UUID):
    try:
        PersonalDocumentService.delete(current_user.id, file_id)
        flash("Файл удалён.", "info")
    except NotFoundError:
        abort(404)
    return redirect(url_for("documents.index"))
