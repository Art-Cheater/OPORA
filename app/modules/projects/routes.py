"""Маршруты модуля проектов."""

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
    PERM_PROJECTS_CREATE,
    PERM_PROJECTS_DELETE,
    PERM_PROJECTS_EDIT,
    PERM_PROJECTS_VIEW,
)
from app.models.communication.comment import Comment
from app.models.enums import EntityType, ProjectStatus
from app.models.files.attachment import Attachment
from app.modules.projects.blueprint import projects_bp
from app.modules.projects.forms import (
    ProjectAttachmentForm,
    ProjectCommentForm,
    ProjectDocumentForm,
    ProjectFilterForm,
    ProjectForm,
)
from app.modules.projects.repositories import ProjectFilter, ProjectRepository
from app.modules.projects.services import ProjectPayload, ProjectService


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
    fp = FieldPermissionService.resolve_field
    u, m = current_user, "projects"
    executor_ids = _uuid_list(form.executor_ids.data or [])
    if project and not FieldPermissionService.can_edit_field(u, m, "executor_ids"):
        executor_ids = ProjectRepository.get_executor_ids(project)
    resp_val = fp(u, m, "responsible_id", form.responsible_id.data, project)
    if isinstance(resp_val, uuid.UUID):
        responsible_id = resp_val
    else:
        responsible_id = _uuid_or_none(str(resp_val) if resp_val else "")
    return ProjectPayload(
        code=fp(u, m, "code", form.code.data, project),
        name=fp(u, m, "name", form.name.data, project),
        description=fp(u, m, "description", form.description.data, project),
        status=fp(u, m, "status", form.status.data, project),
        progress_percent=fp(u, m, "progress_percent", form.progress_percent.data or 0, project),
        start_date=fp(u, m, "start_date", form.start_date.data, project),
        end_date=fp(u, m, "end_date", form.end_date.data, project),
        responsible_id=responsible_id,
        executor_ids=executor_ids,
    )


def _prepare_filter_form(form: ProjectFilterForm) -> None:
    users = ProjectRepository.get_users()
    user_choices = [("", "Любой")] + [(str(item.id), item.full_name) for item in users]
    form.responsible_id.choices = user_choices
    form.executor_id.choices = user_choices


def _prepare_project_form(form: ProjectForm) -> None:
    users = ProjectRepository.get_users()
    user_choices = [("", "Не назначен")] + [(str(item.id), item.full_name) for item in users]
    form.responsible_id.choices = user_choices
    form.executor_ids.choices = [(str(item.id), item.full_name) for item in users]


def _apply_project_create_defaults(form: ProjectForm) -> None:
    from datetime import date, timedelta

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


@projects_bp.route("/")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def index():
    filter_form = ProjectFilterForm(request.args)
    _prepare_filter_form(filter_form)

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

    return render_template(
        "projects/index.html",
        filter_form=filter_form,
        projects_pagination=pagination,
        filters=filters,
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
    return render_template("projects/form.html", form=form, mode="create")


@projects_bp.route("/<uuid:project_id>")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def detail(project_id: uuid.UUID):
    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        flash("Проект не найден.", "danger")
        return redirect(url_for("projects.index"))

    comments = list(
        Comment.query.filter_by(
            entity_type=EntityType.PROJECT.value,
            entity_id=project.id,
            deleted_at=None,
        )
        .order_by(Comment.created_at.desc())
        .all()
    )
    attachments = list(
        Attachment.query.filter_by(
            entity_type=EntityType.PROJECT.value,
            entity_id=project.id,
            deleted_at=None,
        )
        .order_by(Attachment.created_at.desc())
        .all()
    )
    comment_form = ProjectCommentForm()
    document_form = ProjectDocumentForm()
    attachment_form = ProjectAttachmentForm()
    file_items = [
        {
            "name": f.file_name,
            "mime": f.mime_type,
            "preview_url": url_for(
                "projects.download_attachment",
                project_id=project.id,
                attachment_id=f.id,
                inline=1,
            ),
            "download_url": url_for(
                "projects.download_attachment",
                project_id=project.id,
                attachment_id=f.id,
            ),
            "created_at": f.created_at.strftime("%d.%m.%Y %H:%M"),
        }
        for f in attachments
    ]

    if is_ajax():
        return render_template(
            "projects/partials/detail_modal.html",
            project=project,
            comments=comments,
            attachments=attachments,
            file_items=file_items,
            **custom_field_detail_context(_CF, project.id, current_user),
        )

    return render_template(
        "projects/detail.html",
        project=project,
        comments=comments,
        attachments=attachments,
        file_items=file_items,
        comment_form=comment_form,
        document_form=document_form,
        attachment_form=attachment_form,
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
    _prepare_project_form(form)
    if request.method == "GET":
        form.responsible_id.data = str(project.manager_id) if project.manager_id else ""
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
    return render_template("projects/form.html", form=form, mode="edit", project=project)


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
    from app.core.upload_utils import collect_upload_files, save_upload, UploadValidationError

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        flash("Проект не найден.", "danger")
        return redirect(url_for("projects.index"))

    form = ProjectDocumentForm()
    if form.validate_on_submit():
        try:
            files = collect_upload_files(form.files.data, request.files.getlist("files"))
            if files:
                for file_storage in files:
                    saved = save_upload(file_storage, relative_dir=f"projects/{project.id}/docs")
                    ProjectService.add_document(
                        project,
                        title=form.title.data or saved.file_name,
                        document_type=form.document_type.data,
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
                ProjectService.add_document(
                    project,
                    title=form.title.data,
                    document_type=form.document_type.data,
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
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.route("/<uuid:project_id>/document/<uuid:document_id>/download")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def download_document(project_id: uuid.UUID, document_id: uuid.UUID):
    from pathlib import Path

    from flask import current_app, send_file

    from app.core.upload_utils import resolve_download_filename
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

@projects_bp.route("/<uuid:project_id>/attachment", methods=["POST"])
@login_required
@permission_required(PERM_PROJECTS_EDIT)
def add_attachment(project_id: uuid.UUID):
    from app.core.upload_utils import UploadValidationError, collect_upload_files, save_upload

    project = ProjectRepository.get_by_id(project_id)
    if project is None:
        flash("Проект не найден.", "danger")
        return redirect(url_for("projects.index"))

    form = ProjectAttachmentForm()
    files = collect_upload_files(form.files.data, request.files.getlist("files"))
    if files:
        try:
            for file_storage in files:
                saved = save_upload(file_storage, relative_dir=f"projects/{project.id}")
                ProjectService.add_attachment(
                    project,
                    file_name=saved.file_name,
                    mime_type=saved.mime_type,
                    file_size=saved.file_size,
                    storage_key=saved.storage_key,
                    user_id=current_user.id,
                )
            flash(f"Загружено файлов: {len(files)}.", "success")
        except (ValidationError, UploadValidationError) as exc:
            flash(str(exc), "danger")
    else:
        flash("Выберите файлы для загрузки.", "danger")
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.route("/<uuid:project_id>/attachment/<uuid:attachment_id>/download")
@login_required
@permission_required(PERM_PROJECTS_VIEW)
def download_attachment(project_id: uuid.UUID, attachment_id: uuid.UUID):
    from pathlib import Path

    from flask import current_app, send_file
    from app.core.upload_utils import resolve_download_filename
    from app.models.files.attachment import Attachment

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
    path = Path(current_app.config["UPLOAD_FOLDER"]) / attachment.storage_key
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