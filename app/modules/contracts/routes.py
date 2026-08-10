"""Маршруты модуля контрактов."""

from __future__ import annotations

import uuid

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.custom_fields_integration import (
    custom_field_detail_context,
    custom_field_form_context,
    save_custom_fields,
)
from app.core.decorators import permission_required
from app.core.field_permissions import FieldPermissionService
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.core.exceptions import ValidationError
from app.models.auth.constants import (
    PERM_CONTRACTS_CREATE,
    PERM_CONTRACTS_DELETE,
    PERM_CONTRACTS_EDIT,
    PERM_CONTRACTS_VIEW,
)
from app.models.communication.comment import Comment
from app.models.enums import ContractStatus, ContractType, EntityType
from app.modules.contracts.blueprint import contracts_bp
from app.modules.contracts.forms import (
    ContractCommentForm,
    ContractDocumentForm,
    ContractFilterForm,
    ContractForm,
)
from app.modules.contracts.repositories import ContractFilter, ContractRepository
from app.modules.contracts.services import ContractPayload, ContractService


def _uuid_or_none(value: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _contract_payload_from_form(form: ContractForm, contract=None) -> ContractPayload:
    fp = FieldPermissionService.resolve_field
    u, m = current_user, "contracts"
    resp_val = fp(u, m, "responsible_id", form.responsible_id.data, contract)
    if isinstance(resp_val, uuid.UUID):
        responsible_id = resp_val
    else:
        responsible_id = _uuid_or_none(str(resp_val) if resp_val else "")
    return ContractPayload(
        contract_type=fp(u, m, "contract_type", form.contract_type.data, contract),
        number=fp(u, m, "number", form.number.data, contract),
        title=fp(u, m, "title", form.title.data, contract),
        description=fp(u, m, "description", form.description.data, contract),
        status=fp(u, m, "status", form.status.data, contract),
        contract_date=fp(u, m, "contract_date", form.contract_date.data, contract),
        responsible_id=responsible_id,
    )


def _prepare_filter_form(form: ContractFilterForm) -> None:
    users = ContractRepository.get_users()
    user_choices = [("", "Любой")] + [(str(item.id), item.full_name) for item in users]
    form.responsible_id.choices = user_choices


def _prepare_contract_form(form: ContractForm) -> None:
    users = ContractRepository.get_users()
    form.responsible_id.choices = [("", "Не назначен")] + [
        (str(item.id), item.full_name) for item in users
    ]


def _apply_contract_create_defaults(form: ContractForm) -> None:
    from datetime import date

    if request.method != "GET":
        return
    form.number.data = ContractRepository.next_number()
    form.title.data = "Новый контракт"
    form.description.data = "Описание контракта"
    form.contract_type.data = ContractType.SUPPLY.value
    form.status.data = ContractStatus.DRAFT.value
    form.contract_date.data = date.today()
    form.responsible_id.data = str(current_user.id)


@contracts_bp.route("/")
@login_required
@permission_required(PERM_CONTRACTS_VIEW)
def index():
    filter_form = ContractFilterForm(request.args)
    _prepare_filter_form(filter_form)

    filters = ContractFilter(
        q=request.args.get("q", ""),
        contract_type=request.args.get("contract_type", ""),
        status=request.args.get("status", ""),
        responsible_id=request.args.get("responsible_id", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = ContractRepository.paginated_list(filters, page=page, per_page=per_page)

    return render_template(
        "contracts/index.html",
        filter_form=filter_form,
        contracts_pagination=pagination,
        filters=filters,
    )


@contracts_bp.route("/table")
@login_required
@permission_required(PERM_CONTRACTS_VIEW)
def table():
    filters = ContractFilter(
        q=request.args.get("q", ""),
        contract_type=request.args.get("contract_type", ""),
        status=request.args.get("status", ""),
        responsible_id=request.args.get("responsible_id", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = ContractRepository.paginated_list(filters, page=page, per_page=per_page)
    html = render_template(
        "contracts/partials/table.html",
        contracts_pagination=pagination,
    )
    pager = render_template(
        "contracts/partials/pagination.html",
        contracts_pagination=pagination,
    )
    return jsonify({"table_html": html, "pagination_html": pager})


_CF = "contracts"


def _cf_form(entity_id=None):
    return custom_field_form_context(_CF, entity_id)


@contracts_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_CONTRACTS_CREATE)
def create():
    form = ContractForm()
    _prepare_contract_form(form)
    _apply_contract_create_defaults(form)

    if form.validate_on_submit():
        try:
            payload = _contract_payload_from_form(form)
            created = ContractService.create_contract(payload, current_user.id)
            save_custom_fields(_CF, created.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Контракт успешно создан.", id=str(created.id))
            flash("Контракт успешно создан.", "success")
            return redirect(url_for("contracts.detail", contract_id=created.id))
        except (ValidationError, ValueError) as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=render_template(
                        "contracts/partials/form_modal.html",
                        form=form,
                        form_action=url_for("contracts.create"),
                        **_cf_form(),
                    ),
                )
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(
            form_errors_message(form),
            html=render_template(
                "contracts/partials/form_modal.html",
                form=form,
                form_action=url_for("contracts.create"),
                        **_cf_form(),
            ),
        )

    if is_ajax():
        return render_template(
            "contracts/partials/form_modal.html",
            form=form,
            form_action=url_for("contracts.create"),
                        **_cf_form(),
        )
    return render_template("contracts/form.html", form=form, mode="create")


@contracts_bp.route("/<uuid:contract_id>")
@login_required
@permission_required(PERM_CONTRACTS_VIEW)
def detail(contract_id: uuid.UUID):
    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))

    comments = list(
        Comment.query.filter_by(
            entity_type=EntityType.CONTRACT.value,
            entity_id=contract.id,
            deleted_at=None,
        )
        .order_by(Comment.created_at.desc())
        .all()
    )
    comment_form = ContractCommentForm()
    document_form = ContractDocumentForm()
    file_items = [
        {
            "name": doc.file_name or doc.title,
            "mime": doc.mime_type,
            "preview_url": url_for(
                "contracts.download_document",
                contract_id=contract.id,
                document_id=doc.id,
                inline=1,
            ),
            "download_url": url_for(
                "contracts.download_document",
                contract_id=contract.id,
                document_id=doc.id,
            ),
            "created_at": doc.created_at.strftime("%d.%m.%Y %H:%M") if doc.created_at else None,
        }
        for doc in contract.documents
        if doc.deleted_at is None and doc.storage_key and doc.file_name
    ]

    if is_ajax():
        return render_template(
            "contracts/partials/detail_modal.html",
            contract=contract,
            comments=comments,
            file_items=file_items,
            **custom_field_detail_context(_CF, contract.id, current_user),
        )

    return render_template(
        "contracts/detail.html",
        contract=contract,
        comments=comments,
        comment_form=comment_form,
        document_form=document_form,
        file_items=file_items,
    )


@contracts_bp.route("/<uuid:contract_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def edit(contract_id: uuid.UUID):
    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))

    form = ContractForm(obj=contract)
    _prepare_contract_form(form)
    if request.method == "GET":
        form.responsible_id.data = str(contract.responsible_id) if contract.responsible_id else ""

    if form.validate_on_submit():
        try:
            payload = _contract_payload_from_form(form, contract)
            ContractService.update_contract(contract, payload, current_user.id)
            save_custom_fields(_CF, contract.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Контракт обновлён.", id=str(contract.id))
            flash("Контракт обновлён.", "success")
            return redirect(url_for("contracts.detail", contract_id=contract.id))
        except (ValidationError, ValueError) as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=render_template(
                        "contracts/partials/form_modal.html",
                        form=form,
                        form_action=url_for("contracts.edit", contract_id=contract.id),
                        **_cf_form(contract.id),
                    ),
                )
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(
            form_errors_message(form),
            html=render_template(
                "contracts/partials/form_modal.html",
                form=form,
                form_action=url_for("contracts.edit", contract_id=contract.id),
                        **_cf_form(contract.id),
            ),
        )

    if is_ajax():
        return render_template(
            "contracts/partials/form_modal.html",
            form=form,
            form_action=url_for("contracts.edit", contract_id=contract.id),
                        **_cf_form(contract.id),
        )
    return render_template("contracts/form.html", form=form, mode="edit", contract=contract)


@contracts_bp.route("/<uuid:contract_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_DELETE)
def delete(contract_id: uuid.UUID):
    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        return ajax_error("Контракт не найден.", status=404)
    try:
        ContractService.delete_contract(contract, current_user.id)
        return ajax_ok("Контракт удалён.")
    except ValidationError as exc:
        return ajax_error(str(exc))


@contracts_bp.route("/<uuid:contract_id>/comment", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def add_comment(contract_id: uuid.UUID):
    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))

    form = ContractCommentForm()
    if form.validate_on_submit():
        try:
            ContractService.add_comment(contract, form.body.data, current_user.id)
            flash("Комментарий добавлен.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


@contracts_bp.route("/<uuid:contract_id>/document", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def add_document(contract_id: uuid.UUID):
    from app.core.upload_utils import UploadValidationError, collect_upload_files, save_upload

    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))

    form = ContractDocumentForm()
    if form.validate_on_submit():
        try:
            files = collect_upload_files(form.files.data, request.files.getlist("files"))
            if files:
                for file_storage in files:
                    saved = save_upload(file_storage, relative_dir=f"contracts/{contract.id}/docs")
                    ContractService.add_document(
                        contract,
                        title=form.title.data or saved.file_name,
                        document_number=form.document_number.data,
                        document_date=form.document_date.data,
                        description=form.description.data,
                        file_name=saved.file_name,
                        mime_type=saved.mime_type,
                        storage_key=saved.storage_key,
                        user_id=current_user.id,
                    )
                flash(f"Добавлено документов: {len(files)}.", "success")
            else:
                ContractService.add_document(
                    contract,
                    title=form.title.data,
                    document_number=form.document_number.data,
                    document_date=form.document_date.data,
                    description=form.description.data,
                    file_name=None,
                    mime_type=None,
                    storage_key=None,
                    user_id=current_user.id,
                )
                flash("Документ добавлен.", "success")
        except (ValidationError, UploadValidationError) as exc:
            flash(str(exc), "danger")
    else:
        flash("Проверьте корректность данных документа.", "danger")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


@contracts_bp.route("/<uuid:contract_id>/document/<uuid:document_id>/download")
@login_required
@permission_required(PERM_CONTRACTS_VIEW)
def download_document(contract_id: uuid.UUID, document_id: uuid.UUID):
    from pathlib import Path

    from flask import abort, current_app, send_file

    from app.core.upload_utils import resolve_download_filename
    from app.models.contracts.contract_document import ContractDocument

    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        abort(404)
    document = ContractDocument.query.filter_by(
        id=document_id,
        contract_id=contract.id,
        deleted_at=None,
    ).first()
    if document is None or not document.storage_key:
        abort(404)
    path = Path(current_app.config["UPLOAD_FOLDER"]) / document.storage_key
    if not path.is_file():
        abort(404)
    inline = request.args.get("inline") == "1"
    return send_file(
        path,
        mimetype=document.mime_type or "application/octet-stream",
        as_attachment=not inline,
        download_name=resolve_download_filename(
            document.file_name,
            storage_key=document.storage_key,
            mime_type=document.mime_type,
        ),
    )