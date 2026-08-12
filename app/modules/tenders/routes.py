"""Маршруты заявок на торги."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.core.upload_utils import collect_upload_files, resolve_download_filename, save_upload
from app.models.auth.constants import (
    PERM_CONTRACTS_CREATE,
    PERM_TENDERS_CREATE,
    PERM_TENDERS_EDIT,
    PERM_TENDERS_VIEW,
)
from app.models.enums import TenderApplicationStatus
from app.modules.tenders.blueprint import tenders_bp
from app.modules.tenders.forms import (
    TENDER_STATUS_LABELS,
    TenderDocumentForm,
    TenderFilterForm,
    TenderForm,
)
from app.modules.tenders.repositories import TenderFilter, TenderRepository
from app.modules.tenders.services import TenderPayload, TenderService


def _uuid_or_none(value: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _uuid_list(values: list[str]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for value in values or []:
        parsed = _uuid_or_none(value)
        if parsed is not None:
            result.append(parsed)
    return result


def _prepare_form(form: TenderForm, extra_project_ids: list[uuid.UUID] | None = None) -> None:
    users = TenderRepository.get_users()
    form.responsible_id.choices = [("", "Не назначен")] + [
        (str(u.id), u.full_name) for u in users
    ]
    from app.modules.objects.repositories import ObjectRepository

    objects = ObjectRepository.list_all()
    form.object_id.choices = [("", "Не выбран")] + [
        (str(o.id), o.display_address[:120]) for o in objects
    ]
    projects = TenderRepository.selectable_projects(extra_project_ids)
    form.project_ids.choices = [
        (
            str(p.id),
            f"{p.code} — {p.name}" + (f" ({p.work_object.name})" if p.work_object else ""),
        )
        for p in projects
    ]


def _payload(form: TenderForm) -> TenderPayload:
    return TenderPayload(
        number=form.number.data or "",
        title=form.title.data or "",
        description=form.description.data,
        status=form.status.data or TenderApplicationStatus.DRAFT.value,
        responsible_id=_uuid_or_none(form.responsible_id.data or ""),
        project_ids=_uuid_list(form.project_ids.data or []),
        object_id=_uuid_or_none(form.object_id.data or ""),
        work_deadline=form.work_deadline.data,
        published_at=form.published_at.data,
    )


def _render_form_modal(form: TenderForm, form_action: str, modal_title: str):
    return render_template(
        "tenders/partials/form_modal.html",
        form=form,
        form_action=form_action,
        modal_title=modal_title,
    )


@tenders_bp.route("/")
@login_required
@permission_required(PERM_TENDERS_VIEW)
def index():
    filter_form = TenderFilterForm(request.args)
    filters = TenderFilter(
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = TenderRepository.paginated_list(filters, page=page, per_page=per_page)
    return render_template(
        "tenders/index.html",
        filter_form=filter_form,
        pagination=pagination,
        items=pagination.items,
        status_labels=TENDER_STATUS_LABELS,
    )


@tenders_bp.route("/table")
@login_required
@permission_required(PERM_TENDERS_VIEW)
def table():
    filters = TenderFilter(
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = TenderRepository.paginated_list(filters, page=page, per_page=per_page)
    html = render_template(
        "tenders/partials/table.html",
        pagination=pagination,
        items=pagination.items,
        status_labels=TENDER_STATUS_LABELS,
    )
    pager = render_template(
        "tenders/partials/pagination.html",
        pagination=pagination,
    )
    return jsonify({"table_html": html, "pagination_html": pager})


@tenders_bp.route("/new", methods=["GET", "POST"])
@tenders_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required(PERM_TENDERS_CREATE)
def create():
    form = TenderForm()
    preselect = request.args.getlist("project_id")
    _prepare_form(form, _uuid_list(preselect))
    if request.method == "GET":
        form.number.data = TenderRepository.next_number()
        form.status.data = TenderApplicationStatus.DRAFT.value
        form.responsible_id.data = str(current_user.id)
        if preselect:
            form.project_ids.data = preselect
        form.title.data = "Заявка на торги"
    if form.validate_on_submit():
        try:
            tender = TenderService.create(_payload(form), current_user.id)
            flash("Заявка на торги создана.", "success")
            if is_ajax():
                return ajax_ok(
                    "Заявка на торги создана.",
                    redirect_url=url_for("tenders.detail", tender_id=tender.id),
                )
            return redirect(url_for("tenders.detail", tender_id=tender.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=_render_form_modal(form, url_for("tenders.create"), "Новая заявка на торги"),
                )
            flash(str(exc), "danger")
    elif request.method == "POST" and is_ajax():
        return ajax_error(
            form_errors_message(form),
            html=_render_form_modal(form, url_for("tenders.create"), "Новая заявка на торги"),
        )
    if is_ajax() and request.method == "GET":
        return _render_form_modal(form, url_for("tenders.create"), "Новая заявка на торги")
    return render_template("tenders/form.html", form=form, mode="create")


@tenders_bp.route("/<uuid:tender_id>")
@login_required
@permission_required(PERM_TENDERS_VIEW)
def detail(tender_id: uuid.UUID):
    tender = TenderRepository.get_by_id(tender_id)
    if tender is None:
        flash("Заявка на торги не найдена.", "danger")
        return redirect(url_for("tenders.index"))
    doc_form = TenderDocumentForm()
    project_docs = TenderService.linked_project_documents(tender)
    return render_template(
        "tenders/detail.html",
        tender=tender,
        status_labels=TENDER_STATUS_LABELS,
        doc_form=doc_form,
        project_docs=project_docs,
        can_create_contract=(
            tender.status == TenderApplicationStatus.WON.value
            and current_user.has_permission(PERM_CONTRACTS_CREATE)
        ),
    )


@tenders_bp.route("/<uuid:tender_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_TENDERS_EDIT)
def edit(tender_id: uuid.UUID):
    tender = TenderRepository.get_by_id(tender_id)
    if tender is None:
        flash("Заявка на торги не найдена.", "danger")
        return redirect(url_for("tenders.index"))
    current_ids = [link.project_id for link in tender.project_links if link.deleted_at is None]
    form = TenderForm()
    _prepare_form(form, current_ids)
    if request.method == "GET":
        form.number.data = tender.number
        form.title.data = tender.title
        form.description.data = tender.description
        form.status.data = tender.status
        form.responsible_id.data = str(tender.responsible_id) if tender.responsible_id else ""
        form.project_ids.data = [str(i) for i in current_ids]
        form.object_id.data = str(tender.object_id) if tender.object_id else ""
        form.work_deadline.data = tender.work_deadline
        form.published_at.data = tender.published_at
    if form.validate_on_submit():
        try:
            TenderService.update(tender, _payload(form), current_user.id)
            flash("Заявка на торги сохранена.", "success")
            if is_ajax():
                return ajax_ok(
                    "Заявка на торги сохранена.",
                    redirect_url=url_for("tenders.detail", tender_id=tender.id),
                )
            return redirect(url_for("tenders.detail", tender_id=tender.id))
        except ValidationError as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=_render_form_modal(
                        form,
                        url_for("tenders.edit", tender_id=tender.id),
                        "Редактирование заявки на торги",
                    ),
                )
            flash(str(exc), "danger")
    elif request.method == "POST" and is_ajax():
        return ajax_error(
            form_errors_message(form),
            html=_render_form_modal(
                form,
                url_for("tenders.edit", tender_id=tender.id),
                "Редактирование заявки на торги",
            ),
        )
    if is_ajax() and request.method == "GET":
        return _render_form_modal(
            form,
            url_for("tenders.edit", tender_id=tender.id),
            "Редактирование заявки на торги",
        )
    return render_template("tenders/form.html", form=form, mode="edit", tender=tender)


@tenders_bp.route("/<uuid:tender_id>/document", methods=["POST"])
@login_required
@permission_required(PERM_TENDERS_EDIT)
def add_document(tender_id: uuid.UUID):
    tender = TenderRepository.get_by_id(tender_id)
    if tender is None:
        flash("Заявка на торги не найдена.", "danger")
        return redirect(url_for("tenders.index"))
    form = TenderDocumentForm()
    if not form.validate_on_submit():
        flash(form_errors_message(form) or "Проверьте данные документа.", "danger")
        return redirect(url_for("tenders.detail", tender_id=tender.id))

    files = collect_upload_files(form.files.data)
    storage_key = file_name = mime_type = None
    if files:
        try:
            saved = save_upload(files[0], relative_dir=f"tenders/{tender.id}")
            storage_key = saved.storage_key
            file_name = saved.file_name
            mime_type = saved.mime_type
        except Exception as exc:  # noqa: BLE001
            flash(str(exc), "danger")
            return redirect(url_for("tenders.detail", tender_id=tender.id))

    try:
        TenderService.add_document(
            tender,
            title=form.title.data,
            document_type=form.document_type.data,
            document_number=form.document_number.data,
            document_date=form.document_date.data,
            description=form.description.data,
            file_name=file_name,
            mime_type=mime_type,
            storage_key=storage_key,
            user_id=current_user.id,
        )
        flash("Документ добавлен.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("tenders.detail", tender_id=tender.id))


@tenders_bp.route("/<uuid:tender_id>/documents/<uuid:document_id>/download")
@login_required
@permission_required(PERM_TENDERS_VIEW)
def download_document(tender_id: uuid.UUID, document_id: uuid.UUID):
    tender = TenderRepository.get_by_id(tender_id)
    if tender is None:
        flash("Заявка на торги не найдена.", "danger")
        return redirect(url_for("tenders.index"))
    doc = next((d for d in tender.documents if d.id == document_id and d.deleted_at is None), None)
    if doc is None or not doc.storage_key:
        flash("Файл не найден.", "danger")
        return redirect(url_for("tenders.detail", tender_id=tender.id))
    path = Path(current_app.config["UPLOAD_FOLDER"]) / doc.storage_key
    return send_file(
        path,
        as_attachment=True,
        download_name=resolve_download_filename(doc.file_name or doc.title),
        mimetype=doc.mime_type or "application/octet-stream",
    )
