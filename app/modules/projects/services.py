"""Сервисы модуля проектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from flask import request

from app.core.audit_service import AuditService
from app.core.exceptions import NotFoundError, ValidationError
from app.extensions import db
from app.models.communication.comment import Comment
from app.models.enums import AuditAction, EntityType, ProjectMemberRole, WorkObjectStatus
from app.models.files.attachment import Attachment
from app.models.projects.project import Project
from app.models.projects.project_document import ProjectDocument
from app.models.projects.project_history import ProjectHistory
from app.models.projects.project_member import ProjectMember
from app.models.work_objects.work_object import WorkObject


@dataclass
class ProjectPayload:
    code: str
    name: str
    description: str | None
    status: str
    progress_percent: int
    start_date: date | None
    end_date: date | None
    responsible_id: uuid.UUID | None
    executor_ids: list[uuid.UUID]
    object_id: uuid.UUID | None


class ProjectService:
    """CRUD + аудит + история изменений проектов."""

    TRACKED_FIELDS = [
        "code",
        "name",
        "description",
        "status",
        "progress_percent",
        "start_date",
        "end_date",
        "manager_id",
        "object_id",
    ]

    @staticmethod
    def _client_ip() -> str | None:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr

    @staticmethod
    def _user_agent() -> str | None:
        return request.headers.get("User-Agent")

    @staticmethod
    def _normalize_text(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @classmethod
    def validate_payload(cls, payload: ProjectPayload, *, project: Project | None = None) -> None:
        if not payload.code.strip():
            raise ValidationError("Код проекта обязателен.")
        if not payload.name.strip():
            raise ValidationError("Название проекта обязательно.")
        if payload.object_id is None:
            raise ValidationError("Объект обязателен.")
        if payload.progress_percent < 0 or payload.progress_percent > 100:
            raise ValidationError("Процент готовности должен быть от 0 до 100.")
        if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
            raise ValidationError("Дата начала не может быть позже даты окончания.")

        work_object = db.session.scalar(
            db.select(WorkObject).where(
                WorkObject.id == payload.object_id,
                WorkObject.active_filter(),
            )
        )
        if work_object is None:
            raise ValidationError("Объект не найден.")

        other = db.session.scalar(
            db.select(Project).where(
                Project.object_id == payload.object_id,
                Project.active_filter(),
                Project.status.notin_(
                    ["completed", "cancelled", "archived"]
                ),
            )
        )
        if other is not None and (project is None or other.id != project.id):
            raise ValidationError("У этого объекта уже есть активный проект.")

        if project is None or project.object_id != payload.object_id:
            # Статус «в контракте» из плана освещения — справочный; блокируем только торги/завершённые
            if work_object.status in (
                WorkObjectStatus.IN_TENDER.value,
                WorkObjectStatus.COMPLETED.value,
                WorkObjectStatus.ARCHIVED.value,
            ):
                raise ValidationError("Объект занят (на торгах, завершён или в архиве).")

    @staticmethod
    def _snapshot(project: Project) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field in ProjectService.TRACKED_FIELDS:
            value = getattr(project, field)
            if isinstance(value, uuid.UUID):
                data[field] = str(value)
            elif isinstance(value, date):
                data[field] = value.isoformat()
            else:
                data[field] = value
        data["executor_ids"] = [
            str(member.user_id)
            for member in project.active_members
            if member.role_in_project == ProjectMemberRole.EXECUTOR.value
        ]
        return data

    @staticmethod
    def _diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
        changes: dict[str, dict[str, Any]] = {}
        keys = set(old.keys()) | set(new.keys())
        for key in keys:
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}
        return changes

    @classmethod
    def _log_audit(
        cls,
        user_id: uuid.UUID,
        action: str,
        entity_id: uuid.UUID,
        description: str,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
    ) -> None:
        AuditService.log(
            user_id=user_id,
            action=action,
            entity_type=EntityType.PROJECT.value,
            entity_id=entity_id,
            description=description,
            old_values=old_values,
            new_values=new_values,
        )

    @staticmethod
    def _log_history(
        project: Project,
        user_id: uuid.UUID,
        action: str,
        comment: str | None,
        details: dict[str, Any] | None,
        previous_status: str | None = None,
    ) -> None:
        db.session.add(
            ProjectHistory(
                project_id=project.id,
                status=project.status,
                previous_status=previous_status,
                action=action,
                comment=comment,
                details=details,
                changed_by=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    @classmethod
    def _sync_executors(
        cls,
        project: Project,
        executor_ids: list[uuid.UUID],
        user_id: uuid.UUID,
    ) -> None:
        desired = set(executor_ids)
        current_members = [
            member
            for member in project.active_members
            if member.role_in_project == ProjectMemberRole.EXECUTOR.value
        ]
        current_ids = {member.user_id for member in current_members}

        for member in current_members:
            if member.user_id not in desired:
                member.soft_delete(user_id)

        for executor_id in desired - current_ids:
            db.session.add(
                ProjectMember(
                    project_id=project.id,
                    user_id=executor_id,
                    role_in_project=ProjectMemberRole.EXECUTOR.value,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )

    @classmethod
    def create_project(cls, payload: ProjectPayload, user_id: uuid.UUID) -> Project:
        cls.validate_payload(payload)
        exists = db.session.scalar(
            db.select(Project).where(
                Project.code == payload.code.strip(),
                Project.active_filter(),
            )
        )
        if exists is not None:
            raise ValidationError("Проект с таким кодом уже существует.")

        project = Project(
            code=payload.code.strip(),
            name=payload.name.strip(),
            description=cls._normalize_text(payload.description),
            status=payload.status,
            progress_percent=payload.progress_percent,
            start_date=payload.start_date,
            end_date=payload.end_date,
            manager_id=payload.responsible_id,
            object_id=payload.object_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(project)
        db.session.flush()
        work_object = db.session.get(WorkObject, payload.object_id)
        if work_object is not None:
            work_object.status = WorkObjectStatus.IN_PROJECT.value
            work_object.updated_by = user_id
        cls._sync_executors(project, payload.executor_ids, user_id)
        db.session.flush()

        snapshot = cls._snapshot(project)
        cls._log_audit(user_id, AuditAction.CREATE.value, project.id, f"Создан проект {project.code}", None, snapshot)
        cls._log_history(project, user_id, "create", "Проект создан", {"created": snapshot})
        db.session.commit()
        return project

    @classmethod
    def update_project(
        cls,
        project: Project,
        payload: ProjectPayload,
        user_id: uuid.UUID,
    ) -> Project:
        cls.validate_payload(payload, project=project)
        old_snapshot = cls._snapshot(project)
        previous_status = project.status
        previous_object_id = project.object_id

        project.code = payload.code.strip()
        project.name = payload.name.strip()
        project.description = cls._normalize_text(payload.description)
        project.status = payload.status
        project.progress_percent = payload.progress_percent
        project.start_date = payload.start_date
        project.end_date = payload.end_date
        project.manager_id = payload.responsible_id
        project.object_id = payload.object_id
        project.updated_by = user_id

        if previous_object_id and previous_object_id != payload.object_id:
            old_obj = db.session.get(WorkObject, previous_object_id)
            if old_obj is not None and old_obj.status == WorkObjectStatus.IN_PROJECT.value:
                old_obj.status = WorkObjectStatus.FREE.value
                old_obj.updated_by = user_id
        work_object = db.session.get(WorkObject, payload.object_id)
        if work_object is not None and work_object.status == WorkObjectStatus.FREE.value:
            work_object.status = WorkObjectStatus.IN_PROJECT.value
            work_object.updated_by = user_id

        cls._sync_executors(project, payload.executor_ids, user_id)
        db.session.flush()

        new_snapshot = cls._snapshot(project)
        changes = cls._diff(old_snapshot, new_snapshot)
        if not changes:
            return project

        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            project.id,
            f"Обновлён проект {project.code}",
            old_snapshot,
            new_snapshot,
        )
        history_action = "status_change" if previous_status != project.status else "update"
        cls._log_history(
            project,
            user_id,
            history_action,
            "Обновление проекта",
            {"changes": changes},
            previous_status=previous_status,
        )
        db.session.commit()
        return project

    @classmethod
    def add_comment(cls, project: Project, body: str, user_id: uuid.UUID) -> Comment:
        body = body.strip()
        if not body:
            raise ValidationError("Комментарий не может быть пустым.")
        comment = Comment(
            author_id=user_id,
            entity_type=EntityType.PROJECT.value,
            entity_id=project.id,
            body=body,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(comment)
        cls._log_audit(user_id, AuditAction.UPDATE.value, project.id, "Добавлен комментарий к проекту", None, {"comment": body})
        cls._log_history(project, user_id, "comment", "Добавлен комментарий", {"comment": body})
        db.session.commit()
        return comment

    @classmethod
    def add_attachment(
        cls,
        project: Project,
        *,
        file_name: str,
        mime_type: str,
        file_size: int,
        storage_key: str,
        user_id: uuid.UUID,
    ) -> Attachment:
        attachment = Attachment(
            uploaded_by=user_id,
            entity_type=EntityType.PROJECT.value,
            entity_id=project.id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            storage_key=storage_key,
            checksum=None,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(attachment)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            project.id,
            f"Добавлен файл к проекту: {file_name}",
            None,
            {"attachment": file_name},
        )
        cls._log_history(project, user_id, "attachment", "Добавлен файл", {"file_name": file_name})
        db.session.commit()
        return attachment

    @classmethod
    def add_document(
        cls,
        project: Project,
        *,
        title: str,
        document_type: str,
        document_number: str | None,
        document_date: date | None,
        description: str | None,
        file_name: str | None,
        mime_type: str | None,
        storage_key: str | None,
        user_id: uuid.UUID,
    ) -> ProjectDocument:
        if not title.strip():
            raise ValidationError("Название документа обязательно.")

        document = ProjectDocument(
            project_id=project.id,
            title=title.strip(),
            document_type=document_type,
            document_number=cls._normalize_text(document_number),
            document_date=document_date,
            description=cls._normalize_text(description),
            file_name=file_name,
            mime_type=mime_type,
            storage_key=storage_key,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(document)
        cls._log_audit(
            user_id,
            AuditAction.UPDATE.value,
            project.id,
            f"Добавлен документ к проекту: {document.title}",
            None,
            {"document": {"title": document.title, "type": document.document_type}},
        )
        cls._log_history(
            project,
            user_id,
            "document",
            "Добавлен документ",
            {"title": document.title, "document_type": document.document_type},
        )
        db.session.commit()
        return document

    @classmethod
    def delete_project(cls, project: Project, user_id: uuid.UUID) -> None:
        code = project.code
        project.soft_delete(deleted_by=user_id)
        cls._log_audit(
            user_id,
            AuditAction.SOFT_DELETE.value,
            project.id,
            f"Удалён проект {code}",
        )
        db.session.commit()

    @staticmethod
    def ensure_project(project_id: str) -> Project:
        project = db.session.get(Project, uuid.UUID(project_id))
        if project is None or project.deleted_at is not None:
            raise NotFoundError("Проект не найден.")
        return project
