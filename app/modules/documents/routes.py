"""Маршруты личных документов и договоров."""

from __future__ import annotations

import uuid
from datetime import date

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import NotFoundError, ValidationError
from app.core.upload_utils import collect_upload_files, resolve_download_filename
from app.models.auth.constants import PERM_DOCUMENTS_USE
from app.modules.documents.blueprint import documents_bp
from app.modules.documents.forms import (
    ContractsFeatureForm,
    PersonalContractEditForm,
    PersonalContractUploadForm,
    PersonalDocumentForm,
)
from app.modules.documents.services import PersonalContractService, PersonalDocumentService


def _file_items(user_id: uuid.UUID) -> list[dict]:
    items = []
    for file in PersonalDocumentService.list_for(user_id):
        items.append(
            {
                "name": file.file_name,
                "mime": file.mime_type,
                "preview_url": url_for("documents.download", file_id=file.id, inline=1),
                "download_url": url_for("documents.download", file_id=file.id),
                "delete_url": url_for("documents.delete", file_id=file.id),
                "can_delete": True,
                "created_at": file.created_at.strftime("%d.%m.%Y %H:%M") if file.created_at else "",
            }
        )
    return items


def _contract_rows(user_id: uuid.UUID) -> list[dict]:
    today = date.today()
    rows = []
    for item in PersonalContractService.list_for(user_id):
        days_left = (item.ends_on - today).days if item.ends_on else None
        rows.append(
            {
                "contract": item,
                "days_left": days_left,
                "edit_form": PersonalContractEditForm(
                    title=item.title,
                    description=item.description or "",
                    ends_on=item.ends_on,
                    reminders_enabled=item.reminders_enabled,
                ),
                "preview_url": url_for(
                    "documents.download",
                    file_id=item.attachment_id,
                    inline=1,
                ),
                "download_url": url_for("documents.download", file_id=item.attachment_id),
            }
        )
    return rows


@documents_bp.route("/")
@login_required
@permission_required(PERM_DOCUMENTS_USE)
def index():
    contracts_on = bool(current_user.personal_contracts_enabled)
    tab = (request.args.get("tab") or "files").strip().lower()
    if tab not in {"files", "contracts"} or not contracts_on:
        tab = "files"
    feature_form = ContractsFeatureForm(enabled=contracts_on)
    return render_template(
        "documents/index.html",
        form=PersonalDocumentForm(),
        contract_form=PersonalContractUploadForm(),
        feature_form=feature_form,
        file_items=_file_items(current_user.id),
        contract_rows=_contract_rows(current_user.id) if contracts_on else [],
        contracts_enabled=contracts_on,
        active_tab=tab,
    )


@documents_bp.route("/settings/contracts", methods=["POST"])
@login_required
@permission_required(PERM_DOCUMENTS_USE)
def toggle_contracts():
    form = ContractsFeatureForm()
    if form.validate_on_submit():
        PersonalDocumentService.set_contracts_enabled(current_user, bool(form.enabled.data))
        if form.enabled.data:
            flash("Раздел «Договоры» включён. Можно загружать контракты и получать напоминания.", "success")
            return redirect(url_for("documents.index", tab="contracts"))
        flash("Раздел «Договоры» выключен. Обычные файлы доступны как раньше.", "info")
    return redirect(url_for("documents.index"))


@documents_bp.route("/upload", methods=["POST"])
@login_required
@permission_required(PERM_DOCUMENTS_USE)
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
    return redirect(url_for("documents.index", tab="files"))


@documents_bp.route("/contracts/upload", methods=["POST"])
@login_required
@permission_required(PERM_DOCUMENTS_USE)
def upload_contract():
    if not current_user.personal_contracts_enabled:
        flash("Сначала включите раздел «Договоры».", "warning")
        return redirect(url_for("documents.index"))
    form = PersonalContractUploadForm()
    files = collect_upload_files(form.files.data, request.files.getlist("files"))
    if form.validate_on_submit() or files:
        try:
            if not files:
                raise ValidationError("Выберите хотя бы один файл договора.")
            saved, notes = PersonalContractService.add_from_files(current_user.id, files)
            flash(f"Загружено договоров: {saved}. Название и срок подставились из файла — проверьте карточки.", "success")
            for note in notes[:5]:
                flash(note, "warning")
        except ValidationError as exc:
            flash(str(exc), "danger")
    else:
        flash("Выберите хотя бы один файл.", "danger")
    return redirect(url_for("documents.index", tab="contracts"))


@documents_bp.route("/contracts/<uuid:contract_id>/edit", methods=["POST"])
@login_required
@permission_required(PERM_DOCUMENTS_USE)
def edit_contract(contract_id: uuid.UUID):
    if not current_user.personal_contracts_enabled:
        flash("Раздел «Договоры» выключен.", "warning")
        return redirect(url_for("documents.index"))
    form = PersonalContractEditForm()
    if not form.validate_on_submit():
        flash("Проверьте поля договора.", "danger")
        return redirect(url_for("documents.index", tab="contracts"))
    try:
        PersonalContractService.update(
            current_user.id,
            contract_id,
            title=form.title.data or "",
            description=form.description.data,
            ends_on=form.ends_on.data,
            reminders_enabled=bool(form.reminders_enabled.data),
        )
        flash("Договор обновлён.", "success")
    except NotFoundError:
        abort(404)
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("documents.index", tab="contracts"))


@documents_bp.route("/contracts/<uuid:contract_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_DOCUMENTS_USE)
def delete_contract(contract_id: uuid.UUID):
    try:
        PersonalContractService.delete(current_user.id, contract_id)
        flash("Договор удалён.", "info")
    except NotFoundError:
        abort(404)
    return redirect(url_for("documents.index", tab="contracts"))


@documents_bp.route("/<uuid:file_id>")
@login_required
@permission_required(PERM_DOCUMENTS_USE)
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
@permission_required(PERM_DOCUMENTS_USE)
def delete(file_id: uuid.UUID):
    try:
        PersonalDocumentService.delete(current_user.id, file_id)
        flash("Файл удалён.", "info")
    except NotFoundError:
        abort(404)
    return redirect(url_for("documents.index", tab="files"))
