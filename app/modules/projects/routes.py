"""Маршруты модуля проектов."""

from __future__ import annotations

import uuid

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, load_only, noload

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
from app.extensions import db
from app.models.auth.constants import (
    PERM_PROJECTS_CREATE,
    PERM_PROJECTS_DELETE,
    PERM_PROJECTS_EDIT,
    PERM_PROJECTS_VIEW,
)
from app.models.auth.user import User
from app.models.communication.comment import Comment
from app.models.enums import EntityType, ProjectStatus
from app.models.files.attachment import Attachment
from app.modules.projects.blueprint import projects_bp
from app.modules.projects.forms import (
    ProjectCommentForm,
    ProjectDocumentForm,
    ProjectFilterForm,
    ProjectForm,
    DOCUMENT_TYPE_LABELS,
)
from app.modules.projects.repositories import ProjectFilter, ProjectRepository
from app.modules.projects.services import ProjectPayload, ProjectService


def _users_by_ids(user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not user_ids:
        return {}
    rows = db.session.scalars(
        db.select(User)
        .options(load_only(User.id, User.full_name), noload(User.user_roles), noload(User.login_logs))
        .where(User.id.in_(user_ids))
    ).all()
    return {u.id: u for u in rows}


def _uuid_or_none(value: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _uuid_list(values: list[str]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for value in values:
        parsed = _uuid_or_none(value)
        if parsed is not None:
            result.append(parsed)
    return result


def _project_payload_from_form(form: ProjectForm, project=None) -> ProjectPayload:
    from app.core.builtin_field_service import BuiltinFieldService as BFS
    from app.models.enums import ProjectStatus

    fp = FieldPermissionService.resolve_field
    u, m = current_user, "projects"

    def field(code, submitted, default=None):
        raw = fp(u, m, code, submitted, project)
        return BFS.value_or_default(m, code, raw, default=default, entity=project)

    executor_ids = _uuid_list(form.executor_ids.data or [])
    if project and not FieldPermissionService.can_edit_field(u, m, "executor_ids"):
        executor_ids = ProjectRepository.get_executor_ids(project)
    if not BFS.is_visible(m, "executor_ids"):
        if project is not None:
            executor_ids = ProjectRepository.get_executor_ids(project)
        elif not executor_ids:
            executor_ids = []

    resp_val = field("responsible_id", form.responsible_id.data, default=None)
    if isinstance(resp_val, uuid.UUID):
        responsible_id = resp_val
    else:
        responsible_id = _uuid_or_none(str(resp_val) if resp_val else "")
    object_val = field("object_id", form.object_id.data, default=None)
    if isinstance(object_val, uuid.UUID):
        object_id = object_val
    else:
        object_id = _uuid_or_none(str(object_val) if object_val else "")
    return ProjectPayload(
        code=field("code", form.code.data, default=ProjectRepository.next_code()),
        name=field("name", form.name.data, default="Без названия"),
        description=field("description", form.description.data, default=""),
        status=field("status", form.status.data, default=ProjectStatus.DRAFT.value),
        progress_percent=field("progress_percent", form.progress_percent.data or 0, default=0),
        start_date=field("start_date", form.start_date.data, default=None),
        end_date=field("end_date", form.end_date.data, default=None),
        responsible_id=responsible_id,
        executor_ids=executor_ids,
        object_id=object_id,
        sip_meters=field("sip_meters", form.sip_meters.data, default=None),
        cable_meters=field("cable_meters", form.cable_meters.data, default=None),
        poles_count=field("poles_count", form.poles_count.data, default=None),
        lights_count=field("lights_count", form.lights_count.data, default=None),
        shuno_count=field("shuno_count", form.shuno_count.data, default=None),
        sip_meters_fact=field("sip_meters_fact", form.sip_meters_fact.data, default=None),
        cable_meters_fact=field("cable_meters_fact", form.cable_meters_fact.data, default=None),
        poles_count_fact=field("poles_count_fact", form.poles_count_fact.data, default=None),
        lights_count_fact=field("lights_count_fact", form.lights_count_fact.data, default=None),
        shuno_count_fact=field("shuno_count_fact", form.shuno_count_fact.data, default=None),
    )


def _prepare_filter_form(form: ProjectFilterForm) -> None:
    users = ProjectRepository.get_users()
    user_choices = [("", "Любой")] + [(str(item.id), item.full_name) for item in users]
    form.responsible_id.choices = user_choices
    form.executor_id.choices = user_choices


def _prepare_project_form(form: ProjectForm, project=None) -> None:
    from app.core.builtin_field_service import BuiltinFieldService
    from app.modules.objects.repositories import ObjectRepository

    users = ProjectRepository.get_users()
    user_choices = [("", "Не назначен")] + [(str(item.id), item.full_name) for item in users]
    form.responsible_id.choices = user_choices
    form.executor_ids.choices = [(str(item.id), item.full_name) for item in users]

    current_object_id = project.object_id if project else None
    if current_object_id is None:
        raw = (
            request.form.get("object_id")
            or request.args.get("object_id")
            or (form.object_id.data if form.object_id.data else "")
        )
        current_object_id = _uuid_or_none(str(raw) if raw else "")

    # С объектом из URL — не грузим весь справочник свободных (быстрее открытие формы)
    if project is None and current_object_id is not None and request.args.get("object_id"):
        obj = ObjectRepository.get_by_id(current_object_id)
        if obj is not None:
            form.object_id.choices = [
                (str(obj.id), ObjectRepository.label_for_select(obj)),
            ]
        else:
            form.object_id.choices = [("", "Объект не найден")]
    else:
        objects = ObjectRepository.list_free_or_current(
            current_object_id,
            extra_ids=[current_object_id] if current_object_id else None,
        )
        form.object_id.choices = [("", "Выберите объект")] + [
            (str(obj.id), ObjectRepository.label_for_select(obj)) for obj in objects
        ]
    form.object_id.render_kw = {
        **(form.object_id.render_kw or {}),
        "data-choice-url": url_for("objects.api_choices", free_only=1),
        "data-choice-placeholder": "Начните вводить адрес…",
    }
    BuiltinFieldService.apply_to_form(form, "projects")


def _apply_project_create_defaults(form: ProjectForm) -> None:
    from datetime import date, timedelta

    from app.modules.objects.repositories import ObjectRepository
    from app.modules.objects.services import ObjectService

    if request.method != "GET":
        return
    form.code.data = ProjectRepository.next_code()
    form.name.data = "Новый проект"
    form.description.data = "Описание проекта"
    form.status.data = ProjectStatus.DRAFT.value
    form.progress_percent.data = 0
    form.start_date.data = date.today()
    form.end_date.data = date.today() + timedelta(days=90)
    form.responsible_id.data = str(current_user.id)

    object_id = request.args.get("object_id", "")
    if object_id:
        form.object_id.data = object_id
        obj = ObjectRepository.get_by_id(object_id)
        if obj is not None:
            form.name.data = (obj.display_address or obj.name or "Новый проект")[:500]
            if obj.result_text:
                form.description.data = obj.result_text[:5000]
            suggested = ObjectService.suggested_project_status(obj.result_text)
            status_arg = request.args.get("status", "")
            if status_arg in {ProjectStatus.DRAFT.value, ProjectStatus.ACTIVE.value}:
                form.status.data = status_arg
            elif suggested:
                form.status.data = suggested
            if form.status.data == ProjectStatus.ACTIVE.value:
                form.progress_percent.data = 10


@projects_bp.route("/")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def index():
    filter_form = ProjectFilterForm(request.args)
    _prepare_filter_form(filter_form)
    return render_template(
        "projects/index.html",
        filter_form=filter_form,
    )


@projects_bp.route("/table")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def table():
    filters = ProjectFilter(
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        responsible_id=request.args.get("responsible_id", ""),
        executor_id=request.args.get("executor_id", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
        sort_by=request.args.get("sort_by", "created_at"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = ProjectRepository.paginated_list(filters, page=page, per_page=per_page)
    html = render_template(
        "projects/partials/table.html",
        projects_pagination=pagination,
    )
    pager = render_template(
        "projects/partials/pagination.html",
        projects_pagination=pagination,
    )
    return jsonify({"table_html": html, "pagination_html": pager})


_CF = "projects"


def _cf_form(entity_id=None):
    return custom_field_form_context(_CF, entity_id)


@projects_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_PROJECTS_CREATE)
def create():
    form = ProjectForm()
    _prepare_project_form(form)
    _apply_project_create_defaults(form)

    if form.validate_on_submit():
        try:
            payload = _project_payload_from_form(form)
            created = ProjectService.create_project(payload, current_user.id)
            save_custom_fields(_CF, created.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Проект успешно создан.", id=str(created.id))
            flash("Проект успешно создан.", "success")
            return redirect(url_for("projects.detail", project_id=created.id))
        except (ValidationError, ValueError) as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=render_template(
                        "projects/partials/form_modal.html",
                        form=form,
                        form_action=url_for("projects.create"),
                        **_cf_form(),
                    ),
                )
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(form_errors_message(form), html=render_template(
                "projects/partials/form_modal.html",
                form=form,
                form_action=url_for("projects.create"),
                        **_cf_form(),
            ))

    if is_ajax():
        return render_template(
            "projects/partials/form_modal.html",
            form=form,
            form_action=url_for("projects.create"),
                        **_cf_form(),
        )
    return render_template(
        "projects/form.html",
        form=form,
        mode="create",
        **_cf_form(),
    )


@projects_bp.route("/<uuid:project_id>")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def detail(project_id: uuid.UUID):
    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        flash("Проект не найден.", "danger")
        return redirect(url_for("projects.index"))

    comments = list(
        db.session.scalars(
            db.select(Comment)
            .options(
                joinedload(Comment.author).options(
                    load_only(User.id, User.full_name),
                    noload(User.user_roles),
                    noload(User.login_logs),
                ),
                noload(Comment.replies),
                noload(Comment.parent),
            )
            .where(
                Comment.entity_type == EntityType.PROJECT.value,
                Comment.entity_id == project.id,
                Comment.deleted_at.is_(None),
            )
            .order_by(Comment.created_at.desc())
            .limit(50)
        )
    )
    attachments = list(
        Attachment.query.filter_by(
            entity_type=EntityType.PROJECT.value,
            entity_id=project.id,
            deleted_at=None,
        )
        .order_by(Attachment.created_at.desc())
        .limit(50)
        .all()
    )
    documents = ProjectRepository.list_documents(project.id)
    uploader_ids = {
        uid
        for uid in [*(d.created_by for d in documents), *(a.uploaded_by for a in attachments)]
        if uid is not None
    }
    uploaders = _users_by_ids(uploader_ids)
    history = ProjectRepository.list_recent_history(project.id)
    comment_form = ProjectCommentForm()
    document_form = ProjectDocumentForm()
    can_edit_docs = current_user.has_permission(PERM_PROJECTS_EDIT)

    document_items = []
    for doc in documents:
        uploader = uploaders.get(doc.created_by) if doc.created_by else None
        document_items.append(
            {
                "kind": "document",
                "id": doc.id,
                "title": doc.title,
                "type_code": doc.document_type,
                "type_label": DOCUMENT_TYPE_LABELS.get(doc.document_type, doc.document_type),
                "file_name": doc.file_name,
                "mime": doc.mime_type,
                "number": doc.document_number,
                "doc_date": doc.document_date,
                "description": doc.description,
                "uploader": uploader.full_name if uploader else None,
                "created_at": doc.created_at,
                "download_url": (
                    url_for(
                        "projects.download_document",
                        project_id=project.id,
                        document_id=doc.id,
                    )
                    if doc.storage_key
                    else None
                ),
                "preview_url": (
                    url_for(
                        "projects.download_document",
                        project_id=project.id,
                        document_id=doc.id,
                        inline=1,
                    )
                    if doc.storage_key
                    and doc.mime_type
                    and (
                        doc.mime_type.startswith("image/")
                        or doc.mime_type == "application/pdf"
                    )
                    else None
                ),
                "delete_url": (
                    url_for(
                        "projects.delete_document",
                        project_id=project.id,
                        document_id=doc.id,
                    )
                    if can_edit_docs
                    else None
                ),
                "edit_url": (
                    url_for(
                        "projects.edit_document",
                        project_id=project.id,
                        document_id=doc.id,
                    )
                    if can_edit_docs
                    else None
                ),
            }
        )
    for att in attachments:
        uploader = uploaders.get(att.uploaded_by) if att.uploaded_by else None
        document_items.append(
            {
                "kind": "legacy_file",
                "id": att.id,
                "title": att.file_name or "Файл",
                "type_code": "other",
                "type_label": "Прочее (ранее «Файлы»)",
                "file_name": att.file_name,
                "mime": att.mime_type,
                "number": None,
                "doc_date": None,
                "description": None,
                "uploader": uploader.full_name if uploader else None,
                "created_at": att.created_at,
                "download_url": url_for(
                    "projects.download_attachment",
                    project_id=project.id,
                    attachment_id=att.id,
                ),
                "preview_url": (
                    url_for(
                        "projects.download_attachment",
                        project_id=project.id,
                        attachment_id=att.id,
                        inline=1,
                    )
                    if att.mime_type
                    and (
                        att.mime_type.startswith("image/")
                        or att.mime_type == "application/pdf"
                    )
                    else None
                ),
                "delete_url": (
                    url_for(
                        "projects.delete_attachment",
                        project_id=project.id,
                        attachment_id=att.id,
                    )
                    if can_edit_docs
                    else None
                ),
                "edit_url": None,
            }
        )
    document_items.sort(
        key=lambda item: item["created_at"] or 0,
        reverse=True,
    )

    if is_ajax():
        return render_template(
            "projects/partials/detail_modal.html",
            project=project,
            comments=comments,
            document_items=document_items,
            history=history,
            comment_form=comment_form,
            document_form=document_form,
            can_edit_docs=can_edit_docs,
            **custom_field_detail_context(_CF, project.id, current_user),
        )

    return render_template(
        "projects/detail.html",
        project=project,
        comments=comments,
        document_items=document_items,
        history=history,
        comment_form=comment_form,
        document_form=document_form,
        can_edit_docs=can_edit_docs,
        **custom_field_detail_context(_CF, project.id, current_user),
    )


@projects_bp.route("/<uuid:project_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def edit(project_id: uuid.UUID):
    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        flash("Проект не найден.", "danger")
        return redirect(url_for("projects.index"))

    form = ProjectForm(obj=project)
    _prepare_project_form(form, project)
    if request.method == "GET":
        form.responsible_id.data = str(project.manager_id) if project.manager_id else ""
        form.object_id.data = str(project.object_id) if project.object_id else ""
        form.executor_ids.data = [str(item) for item in ProjectRepository.get_executor_ids(project)]

    if form.validate_on_submit():
        try:
            payload = _project_payload_from_form(form, project)
            ProjectService.update_project(project, payload, current_user.id)
            save_custom_fields(_CF, project.id, request.form, current_user)
            if is_ajax():
                return ajax_ok("Проект обновлён.", id=str(project.id))
            flash("Проект обновлён.", "success")
            return redirect(url_for("projects.detail", project_id=project.id))
        except (ValidationError, ValueError) as exc:
            if is_ajax():
                return ajax_error(
                    str(exc),
                    html=render_template(
                        "projects/partials/form_modal.html",
                        form=form,
                        form_action=url_for("projects.edit", project_id=project.id),
                        **_cf_form(project.id),
                    ),
                )
            flash(str(exc), "danger")
    elif is_ajax() and request.method == "POST":
        return ajax_error(
            form_errors_message(form),
            html=render_template(
                "projects/partials/form_modal.html",
                form=form,
                form_action=url_for("projects.edit", project_id=project.id),
                        **_cf_form(project.id),
            ),
        )

    if is_ajax():
        return render_template(
            "projects/partials/form_modal.html",
            form=form,
            form_action=url_for("projects.edit", project_id=project.id),
                        **_cf_form(project.id),
        )
    return render_template(
        "projects/form.html",
        form=form,
        mode="edit",
        project=project,
        **_cf_form(project.id),
    )


@projects_bp.route("/<uuid:project_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_DELETE)
def delete(project_id: uuid.UUID):
    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        return ajax_error("Проект не найден.", status=404)
    try:
        ProjectService.delete_project(project, current_user.id)
        return ajax_ok("Проект удалён.")
    except ValidationError as exc:
        return ajax_error(str(exc))


@projects_bp.route("/<uuid:project_id>/comment", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def add_comment(project_id: uuid.UUID):
    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        flash("Проект не найден.", "danger")
        return redirect(url_for("projects.index"))

    form = ProjectCommentForm()
    if form.validate_on_submit():
        try:
            ProjectService.add_comment(project, form.body.data, current_user.id)
            flash("Комментарий добавлен.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.route("/<uuid:project_id>/document", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def add_document(project_id: uuid.UUID):
    from app.core.upload_utils import UploadValidationError, collect_upload_files, save_upload

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        flash("Проект не найден.", "danger")
        return redirect(url_for("projects.index"))

    form = ProjectDocumentForm()
    if form.validate_on_submit():
        try:
            files = collect_upload_files(form.files.data, request.files.getlist("files"))
            uploads = [
                save_upload(file_storage, relative_dir=f"projects/{project.id}/docs")
                for file_storage in files
            ]
            created = ProjectService.add_documents_from_uploads(
                project,
                document_type=form.document_type.data,
                title=form.title.data,
                document_number=form.document_number.data,
                document_date=form.document_date.data,
                description=form.description.data,
                uploads=uploads,
                user_id=current_user.id,
            )
            if len(created) == 1:
                flash("Документ добавлен.", "success")
            else:
                flash(f"Добавлено документов: {len(created)}.", "success")
        except (ValidationError, UploadValidationError) as exc:
            flash(str(exc), "danger")
    else:
        flash(form_errors_message(form) or "Проверьте корректность данных документа.", "danger")
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.route("/<uuid:project_id>/document/<uuid:document_id>/edit", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def edit_document(project_id: uuid.UUID, document_id: uuid.UUID):
    from app.models.projects.project_document import ProjectDocument

    from app.modules.projects.forms import ProjectDocumentEditForm

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        abort(404)
    document = ProjectDocument.query.filter_by(
        id=document_id,
        project_id=project.id,
        deleted_at=None,
    ).first()
    if document is None:
        flash("Документ не найден.", "danger")
        return redirect(url_for("projects.detail", project_id=project.id))

    form = ProjectDocumentEditForm()
    if form.validate_on_submit():
        try:
            ProjectService.update_document(
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
        flash(form_errors_message(form) or "Проверьте данные документа.", "danger")
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.route("/<uuid:project_id>/document/<uuid:document_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def delete_document(project_id: uuid.UUID, document_id: uuid.UUID):
    from app.models.projects.project_document import ProjectDocument

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        abort(404)
    document = ProjectDocument.query.filter_by(
        id=document_id,
        project_id=project.id,
        deleted_at=None,
    ).first()
    if document is None:
        flash("Документ не найден.", "danger")
        return redirect(url_for("projects.detail", project_id=project.id))
    try:
        ProjectService.delete_document(document, current_user.id)
        flash("Документ удалён.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.route("/<uuid:project_id>/document/<uuid:document_id>/download")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def download_document(project_id: uuid.UUID, document_id: uuid.UUID):
    from flask import send_file

    from app.core.upload_utils import resolve_download_filename, resolve_storage_path
    from app.models.projects.project_document import ProjectDocument

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        abort(404)
    document = ProjectDocument.query.filter_by(
        id=document_id,
        project_id=project.id,
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


@projects_bp.route("/<uuid:project_id>/attachment", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def add_attachment(project_id: uuid.UUID):
    flash('Загрузка перенесена в блок «Документы проекта». Выберите тип документа.', "warning")
    return redirect(url_for("projects.detail", project_id=project_id))


@projects_bp.route("/<uuid:project_id>/attachment/<uuid:attachment_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def delete_attachment(project_id: uuid.UUID, attachment_id: uuid.UUID):
    from app.models.enums import AuditAction

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        abort(404)
    attachment = Attachment.query.filter_by(
        id=attachment_id,
        entity_type=EntityType.PROJECT.value,
        entity_id=project.id,
        deleted_at=None,
    ).first()
    if attachment is None:
        flash("Файл не найден.", "danger")
        return redirect(url_for("projects.detail", project_id=project.id))
    name = attachment.file_name
    attachment.soft_delete(deleted_by=current_user.id)
    ProjectService._log_audit(
        current_user.id,
        AuditAction.SOFT_DELETE.value,
        project.id,
        f"Удалён файл проекта: {name}",
        {"attachment": name},
        None,
    )
    ProjectService._log_history(
        project, current_user.id, "attachment_delete", "Удалён файл", {"file_name": name}
    )
    db.session.commit()
    flash("Файл удалён.", "success")
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.route("/<uuid:project_id>/attachment/<uuid:attachment_id>/download")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def download_attachment(project_id: uuid.UUID, attachment_id: uuid.UUID):
    from flask import send_file

    from app.core.upload_utils import resolve_download_filename, resolve_storage_path

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        abort(404)
    attachment = Attachment.query.filter_by(
        id=attachment_id,
        entity_type="project",
        entity_id=project.id,
        deleted_at=None,
    ).first()
    if attachment is None or not attachment.storage_key:
        abort(404)
    try:
        path = resolve_storage_path(attachment.storage_key)
    except FileNotFoundError:
        abort(404)
    if not path.is_file():
        abort(404)
    inline = request.args.get("inline") == "1"
    return send_file(
        path,
        mimetype=attachment.mime_type or "application/octet-stream",
        as_attachment=not inline,
        download_name=resolve_download_filename(
            attachment.file_name,
            storage_key=attachment.storage_key,
            mime_type=attachment.mime_type,
        ),
    )
