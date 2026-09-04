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
    CONTRACT_DOC_TYPE_LABELS,
    ContractCommentForm,
    ContractDocumentEditForm,
    ContractDocumentForm,
    ContractFilterForm,
    ContractForm,
    ContractLinkObjectForm,
    ContractLinkProjectForm,
)
from app.modules.contracts.repositories import ContractFilter, ContractRepository
from app.modules.contracts.services import ContractPayload, ContractService
from app.modules.objects.repositories import ObjectRepository


def _uuid_or_none(value: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _document_items(contract, *, can_edit: bool) -> list[dict]:
    items = []
    for doc in contract.documents:
        if doc.deleted_at is not None:
            continue
        item = {
            "id": doc.id,
            "title": doc.title,
            "type_code": doc.document_type,
            "type_label": CONTRACT_DOC_TYPE_LABELS.get(doc.document_type, doc.document_type),
            "number": doc.document_number,
            "doc_date": doc.document_date,
            "description": doc.description,
            "file_name": doc.file_name,
            "mime": doc.mime_type,
            "created_at": doc.created_at,
            "uploader": None,
            "preview_url": None,
            "download_url": None,
            "edit_url": None,
            "delete_url": None,
        }
        if doc.storage_key and doc.file_name:
            item["download_url"] = url_for(
                "contracts.download_document",
                contract_id=contract.id,
                document_id=doc.id,
            )
            item["preview_url"] = url_for(
                "contracts.download_document",
                contract_id=contract.id,
                document_id=doc.id,
                inline=1,
            )
        if can_edit:
            item["edit_url"] = url_for(
                "contracts.edit_document",
                contract_id=contract.id,
                document_id=doc.id,
            )
            item["delete_url"] = url_for(
                "contracts.delete_document",
                contract_id=contract.id,
                document_id=doc.id,
            )
        items.append(item)
    return items


def _contract_payload_from_form(form: ContractForm, contract=None) -> ContractPayload:
    from app.core.builtin_field_service import BuiltinFieldService as BFS
    from app.models.enums import ContractStatus, ContractType

    fp = FieldPermissionService.resolve_field
    u, m = current_user, "contracts"

    def field(code, submitted, default=None):
        raw = fp(u, m, code, submitted, contract)
        return BFS.value_or_default(m, code, raw, default=default, entity=contract)

    resp_val = field("responsible_id", form.responsible_id.data, default=None)
    if isinstance(resp_val, uuid.UUID):
        responsible_id = resp_val
    else:
        responsible_id = _uuid_or_none(str(resp_val) if resp_val else "")
    return ContractPayload(
        contract_type=field("contract_type", form.contract_type.data, default=ContractType.OTHER.value),
        number=field("number", form.number.data, default=ContractRepository.next_number()),
        title=field("title", form.title.data, default="Без названия"),
        description=field("description", form.description.data, default=""),
        status=field("status", form.status.data, default=ContractStatus.DRAFT.value),
        contract_date=field("contract_date", form.contract_date.data, default=None),
        end_date=field("end_date", form.end_date.data, default=None),
        responsible_id=responsible_id,
        contractor_name=field("contractor_name", form.contractor_name.data, default=""),
        amount=field("amount", form.amount.data, default=None),
    )


def _prepare_filter_form(form: ContractFilterForm) -> None:
    users = ContractRepository.get_users()
    user_choices = [("", "Любой")] + [(str(item.id), item.full_name) for item in users]
    form.responsible_id.choices = user_choices


def _prepare_contract_form(form: ContractForm, contract=None) -> None:
    from app.core.builtin_field_service import BuiltinFieldService
    from app.extensions import db
    from app.models.projects.project import Project

    users = ContractRepository.get_users()
    form.responsible_id.choices = [("", "Не назначен")] + [
        (str(item.id), item.full_name) for item in users
    ]

    extra_object_ids = []
    current_object_id = None
    if contract is not None:
        for obj in contract.work_objects:
            extra_object_ids.append(obj.id)
        if contract.project and contract.project.object_id:
            extra_object_ids.append(contract.project.object_id)
            current_object_id = contract.project.object_id
    prefill_oid = _uuid_or_none(request.args.get("object_id", "") or request.form.get("object_id", ""))
    if prefill_oid:
        extra_object_ids.append(prefill_oid)
        current_object_id = prefill_oid

    objects = ObjectRepository.list_choices(
        q="",
        limit=20,
        extra_ids=extra_object_ids,
        free_only=False,
        current_id=current_object_id,
    )
    form.object_id.choices = [("", "Не выбран")] + [
        (str(item.id), ObjectRepository.label_for_select(item)) for item in objects
    ]
    form.object_id.render_kw = {
        **(form.object_id.render_kw or {}),
        "data-choice-url": url_for("objects.api_choices"),
        "data-choice-placeholder": "Начните вводить адрес или название…",
    }
    if current_object_id and request.method == "GET":
        form.object_id.data = str(current_object_id)

    projects = list(
        db.session.scalars(
            db.select(Project)
            .where(Project.active_filter())
            .order_by(Project.code.asc())
            .limit(40)
        )
    )
    form.project_id.choices = [("", "Не выбран")] + [
        (str(p.id), f"{p.code} — {p.name}"[:120]) for p in projects
    ]
    if contract is not None and contract.project_id and request.method == "GET":
        form.project_id.data = str(contract.project_id)
        if str(contract.project_id) not in {c[0] for c in form.project_id.choices}:
            form.project_id.choices.append(
                (
                    str(contract.project_id),
                    f"{contract.project.code} — {contract.project.name}"[:120]
                    if contract.project
                    else str(contract.project_id),
                )
            )
    form.project_ids.choices = [(str(p.id), f"{p.code} — {p.name}"[:120]) for p in projects]
    if contract is not None and request.method == "GET":
        form.project_ids.data = [str(project.id) for project in contract.projects]

    BuiltinFieldService.apply_to_form(form, "contracts")


def _apply_contract_create_defaults(form: ContractForm) -> None:
    from datetime import date

    from app.modules.objects.repositories import ObjectRepository
    from app.modules.objects.services import ObjectService

    if request.method != "GET":
        return
    form.number.data = ContractRepository.next_number()
    form.title.data = "Новый контракт"
    form.description.data = "Описание контракта"
    form.contract_type.data = ContractType.WORK.value
    form.status.data = ContractStatus.DRAFT.value
    form.contract_date.data = date.today()
    form.responsible_id.data = str(current_user.id)

    object_id = request.args.get("object_id", "")
    if not object_id:
        return
    obj = ObjectRepository.get_by_id(object_id)
    if obj is None:
        return
    if obj.contract_number:
        form.number.data = obj.contract_number[:100]
    form.title.data = f"Контракт — {obj.display_address}"[:500]
    if obj.contractor_name and hasattr(form, "contractor_name"):
        form.contractor_name.data = obj.contractor_name
    # Сумма контракта, иначе НМЦК (не подменяем поля объекта)
    amount = ObjectService.suggested_contract_amount(obj)
    if amount is not None and hasattr(form, "amount"):
        form.amount.data = amount
    if obj.contract_date:
        form.contract_date.data = obj.contract_date
    if obj.result_text:
        form.description.data = obj.result_text[:5000]


@contracts_bp.route("/")
@login_required
@permission_required(PERM_CONTRACTS_VIEW)
def index():
    filter_form = ContractFilterForm(request.args)
    _prepare_filter_form(filter_form)
    return render_template(
        "contracts/index.html",
        filter_form=filter_form,
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
        contract_date=request.args.get("contract_date", ""),
        end_date_from=request.args.get("end_date_from", ""),
        end_date_to=request.args.get("end_date_to", ""),
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


@contracts_bp.route("/from-tender/<uuid:tender_id>", methods=["GET", "POST"])
@login_required
@permission_required(PERM_CONTRACTS_CREATE)
def create_from_tender(tender_id: uuid.UUID):
    from app.modules.tenders.repositories import TenderRepository

    tender = TenderRepository.get_by_id(tender_id)
    if tender is None:
        flash("Заявка на торги не найдена.", "danger")
        return redirect(url_for("tenders.index"))

    form = ContractForm()
    _prepare_contract_form(form)
    if request.method == "GET":
        form.number.data = ContractRepository.next_number()
        form.title.data = f"Контракт по {tender.number}"
        form.contract_type.data = ContractType.WORK.value
        form.status.data = ContractStatus.DRAFT.value
        form.responsible_id.data = str(current_user.id)

    if form.validate_on_submit():
        try:
            payload = _contract_payload_from_form(form)
            contract = ContractService.create_from_tender(tender, payload, current_user.id)
            save_custom_fields(_CF, contract.id, request.form, current_user)
            flash("Контракт создан из заявки на торги.", "success")
            return redirect(url_for("contracts.detail", contract_id=contract.id))
        except ValidationError as exc:
            flash(str(exc), "danger")
    return render_template(
        "contracts/form.html",
        form=form,
        mode="create",
        tender=tender,
        form_action=url_for("contracts.create_from_tender", tender_id=tender.id),
        **_cf_form(),
    )


@contracts_bp.route("/<uuid:contract_id>/workflow/<action>", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def workflow(contract_id: uuid.UUID, action: str):
    from app.modules.contracts.forms import ContractWorkflowForm

    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        if is_ajax():
            return ajax_error("Контракт не найден.", status=404)
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))

    form = ContractWorkflowForm()
    action_map = {
        "activate": ContractStatus.ACTIVE.value,
        "submit_work_docs": ContractStatus.WORK_DOCS_PENDING.value,
        "approve_work_docs": ContractStatus.IN_PROGRESS.value,
        "submit_ks2": ContractStatus.KS2_PENDING.value,
        "accept_ks2": ContractStatus.COMPLETED.value,
        "reject_ks2": ContractStatus.REJECTED.value,
        "resubmit_ks2": ContractStatus.KS2_PENDING.value,
        "terminate": ContractStatus.TERMINATED.value,
    }
    new_status = action_map.get(action)
    if new_status is None:
        flash("Неизвестное действие.", "danger")
        return redirect(url_for("contracts.detail", contract_id=contract.id))

    if not form.validate_on_submit():
        flash("Не удалось выполнить действие.", "danger")
        return redirect(url_for("contracts.detail", contract_id=contract.id))

    try:
        ContractService.transition(
            contract,
            new_status,
            current_user.id,
            comment=form.comment.data,
            require_rejection_memo=(action == "reject_ks2"),
        )
        flash("Статус контракта обновлён.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


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
            object_id = _uuid_or_none(
                form.object_id.data
                or request.args.get("object_id", "")
                or request.form.get("object_id", "")
            )
            created = ContractService.create_contract(
                payload, current_user.id, object_id=object_id
            )
            project_id = _uuid_or_none(form.project_id.data)
            if project_id is not None:
                from app.extensions import db
                from app.models.projects.project import Project

                project = db.session.get(Project, project_id)
                if project is not None and project.deleted_at is None:
                    ContractService.set_project(created, project, current_user.id)
            for raw_project_id in form.project_ids.data or []:
                project = db.session.get(Project, _uuid_or_none(raw_project_id))
                if project is not None and project.deleted_at is None:
                    ContractService.link_project(created, project, current_user.id)
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
    return render_template(
        "contracts/form.html",
        form=form,
        mode="create",
        form_action=url_for("contracts.create"),
        **_cf_form(),
    )


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
    link_object_form = ContractLinkObjectForm()
    link_project_form = ContractLinkProjectForm()
    objects = ObjectRepository.list_choices(q="", limit=20, free_only=False)
    link_object_form.object_id.choices = [("", "Выберите объект…")] + [
        (str(item.id), ObjectRepository.label_for_select(item)) for item in objects
    ]
    link_object_form.object_id.render_kw = {
        "data-choice-url": url_for("objects.api_choices"),
        "data-choice-placeholder": "Начните вводить адрес или название…",
    }
    from app.extensions import db
    from app.models.projects.project import Project
    projects = list(db.session.scalars(db.select(Project).where(Project.active_filter()).order_by(Project.code.asc()).limit(80)))
    link_project_form.project_id.choices = [("", "Выберите проект…")] + [(str(p.id), f"{p.code} — {p.name}"[:120]) for p in projects]
    can_edit_docs = current_user.has_permission(PERM_CONTRACTS_EDIT)
    document_items = _document_items(contract, can_edit=can_edit_docs)

    ctx = {
        "contract": contract,
        "comments": comments,
        "comment_form": comment_form,
        "document_form": document_form,
        "document_items": document_items,
        "can_edit_docs": can_edit_docs,
        "link_object_form": link_object_form,
        "link_project_form": link_project_form,
        **custom_field_detail_context(_CF, contract.id, current_user),
    }

    if is_ajax() and not request.args.get("full"):
        return render_template("contracts/partials/detail_modal.html", **ctx)

    return render_template("contracts/detail.html", **ctx)


@contracts_bp.route("/<uuid:contract_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def edit(contract_id: uuid.UUID):
    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))

    form = ContractForm(obj=contract)
    _prepare_contract_form(form, contract)
    if request.method == "GET":
        form.responsible_id.data = str(contract.responsible_id) if contract.responsible_id else ""

    if form.validate_on_submit():
        try:
            payload = _contract_payload_from_form(form, contract)
            ContractService.update_contract(contract, payload, current_user.id)
            object_id = _uuid_or_none(form.object_id.data)
            if object_id is not None:
                work_object = ObjectRepository.get_by_id(object_id)
                if work_object is not None:
                    ContractService.link_object(contract, work_object, current_user.id)
            project_id = _uuid_or_none(form.project_id.data)
            from app.extensions import db
            from app.models.projects.project import Project

            if project_id is not None:
                project = db.session.get(Project, project_id)
                if project is not None and project.deleted_at is None:
                    ContractService.set_project(contract, project, current_user.id)
            elif form.project_id.data == "":
                ContractService.set_project(contract, None, current_user.id)
            for raw_project_id in form.project_ids.data or []:
                project = db.session.get(Project, _uuid_or_none(raw_project_id))
                if project is not None and project.deleted_at is None:
                    ContractService.link_project(contract, project, current_user.id)
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
    return render_template(
        "contracts/form.html",
        form=form,
        mode="edit",
        contract=contract,
        form_action=url_for("contracts.edit", contract_id=contract.id),
        **_cf_form(contract.id),
    )


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
        if is_ajax():
            return ajax_error("Контракт не найден.", status=404)
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))

    form = ContractCommentForm()
    if form.validate_on_submit():
        try:
            ContractService.add_comment(contract, form.body.data, current_user.id)
            if is_ajax():
                return ajax_ok("Комментарий добавлен.")
            flash("Комментарий добавлен.", "success")
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(str(exc))
            flash(str(exc), "danger")
    elif is_ajax():
        return ajax_error(form_errors_message(form))
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
            if not files:
                raise ValidationError("Выберите файл для загрузки.")
            uploads = [
                save_upload(file_storage, relative_dir=f"contracts/{contract.id}/docs")
                for file_storage in files
            ]
            created = ContractService.add_documents_from_uploads(
                contract,
                document_type=form.document_type.data,
                title=form.title.data,
                document_number=form.document_number.data,
                document_date=form.document_date.data,
                description=form.description.data,
                uploads=uploads,
                user_id=current_user.id,
            )
            flash(f"Добавлено документов: {len(created)}.", "success")
        except (ValidationError, UploadValidationError) as exc:
            flash(str(exc), "danger")
    else:
        flash("Проверьте корректность данных документа.", "danger")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


@contracts_bp.route("/<uuid:contract_id>/document/<uuid:document_id>/edit", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def edit_document(contract_id: uuid.UUID, document_id: uuid.UUID):
    from app.models.contracts.contract_document import ContractDocument

    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))
    document = ContractDocument.query.filter_by(
        id=document_id, contract_id=contract.id, deleted_at=None
    ).first()
    if document is None:
        flash("Документ не найден.", "danger")
        return redirect(url_for("contracts.detail", contract_id=contract.id))
    form = ContractDocumentEditForm()
    if form.validate_on_submit():
        try:
            ContractService.update_document(
                document,
                title=form.title.data,
                document_type=form.document_type.data,
                document_number=form.document_number.data,
                document_date=form.document_date.data,
                description=form.description.data,
                user_id=current_user.id,
            )
            flash("Документ обновлён.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    else:
        flash(form_errors_message(form), "danger")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


@contracts_bp.route("/<uuid:contract_id>/document/<uuid:document_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def delete_document(contract_id: uuid.UUID, document_id: uuid.UUID):
    from app.models.contracts.contract_document import ContractDocument

    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))
    document = ContractDocument.query.filter_by(
        id=document_id, contract_id=contract.id, deleted_at=None
    ).first()
    if document is None:
        flash("Документ не найден.", "danger")
        return redirect(url_for("contracts.detail", contract_id=contract.id))
    ContractService.delete_document(document, current_user.id)
    flash("Документ удалён.", "success")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


@contracts_bp.route("/<uuid:contract_id>/objects", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def link_object(contract_id: uuid.UUID):
    contract = ContractRepository.get_by_id(contract_id)
    if contract is None:
        flash("Контракт не найден.", "danger")
        return redirect(url_for("contracts.index"))
    form = ContractLinkObjectForm()
    form.object_id.choices = [("", "Выберите объект…")]
    if form.validate_on_submit():
        object_id = _uuid_or_none(form.object_id.data)
        work_object = ObjectRepository.get_by_id(object_id) if object_id else None
        if work_object is None:
            flash("Объект не найден.", "danger")
        else:
            try:
                ContractService.link_object(contract, work_object, current_user.id)
                flash("Объект привязан к контракту.", "success")
            except ValidationError as exc:
                flash(str(exc), "danger")
    else:
        flash(form_errors_message(form), "danger")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


@contracts_bp.route("/<uuid:contract_id>/objects/<uuid:object_id>/unlink", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def unlink_object(contract_id: uuid.UUID, object_id: uuid.UUID):
    contract = ContractRepository.get_by_id(contract_id)
    work_object = ObjectRepository.get_by_id(object_id)
    if contract is None or work_object is None:
        flash("Контракт или объект не найден.", "danger")
        return redirect(url_for("contracts.index"))
    try:
        ContractService.unlink_object(contract, work_object, current_user.id)
        flash("Объект отвязан от контракта.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("contracts.detail", contract_id=contract.id))


@contracts_bp.route("/<uuid:contract_id>/projects", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def link_project(contract_id: uuid.UUID):
    from app.extensions import db
    from app.models.projects.project import Project

    contract = ContractRepository.get_by_id(contract_id)
    form = ContractLinkProjectForm()
    form.project_id.choices = [(str(p.id), p.code) for p in db.session.scalars(db.select(Project).where(Project.active_filter()))]
    project = db.session.get(Project, _uuid_or_none(form.project_id.data)) if form.validate_on_submit() else None
    if contract is None or project is None or project.deleted_at is not None:
        flash("Контракт или проект не найден.", "danger")
    else:
        ContractService.link_project(contract, project, current_user.id)
        flash("Проект привязан к контракту.", "success")
    return redirect(url_for("contracts.detail", contract_id=contract_id))


@contracts_bp.route("/<uuid:contract_id>/projects/<uuid:project_id>/unlink", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTS_EDIT)
def unlink_project(contract_id: uuid.UUID, project_id: uuid.UUID):
    from app.extensions import db
    from app.models.projects.project import Project

    contract = ContractRepository.get_by_id(contract_id)
    project = db.session.get(Project, project_id)
    if contract is None or project is None or project.deleted_at is not None:
        flash("Контракт или проект не найден.", "danger")
    else:
        try:
            ContractService.unlink_project(contract, project, current_user.id)
            flash("Проект отвязан от контракта.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("contracts.detail", contract_id=contract_id))

@contracts_bp.route("/<uuid:contract_id>/document/<uuid:document_id>/download")
@login_required
@permission_required(PERM_CONTRACTS_VIEW)
def download_document(contract_id: uuid.UUID, document_id: uuid.UUID):
    from pathlib import Path

    from flask import abort, current_app, send_file

    from app.core.upload_utils import resolve_download_filename, resolve_storage_path
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
    try:
        path = resolve_storage_path(document.storage_key)
    except FileNotFoundError:
        abort(404)
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
