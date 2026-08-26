"""Сервисы заявок на торги."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.extensions import db
from app.models.enums import (
    AuditAction,
    EntityType,
    ProjectStatus,
    TenderApplicationStatus,
    WorkObjectStatus,
)
from app.models.projects.project import Project
from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_document import TenderDocument
from app.models.tenders.tender_project import TenderProject
from app.models.work_objects.work_object import WorkObject


ACTIVE_OBJECT_BUSY = {
    WorkObjectStatus.IN_PROJECT.value,
    WorkObjectStatus.IN_TENDER.value,
    WorkObjectStatus.IN_CONTRACT.value,
}


@dataclass
class TenderPayload:
    number: str
    title: str
    description: str | None
    status: str
    responsible_id: uuid.UUID | None
    project_ids: list[uuid.UUID]
    object_id: uuid.UUID | None = None
    work_deadline: str | None = None
    published_at: date | None = None


class TenderService:
    @staticmethod
    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @staticmethod
    def parse_deadline_date(value: str | None) -> date | None:
        """Разобрать «Срок выполнения» заявки: дата или год → 31.12 этого года."""
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d{4}", text):
            year = int(text)
            if 2000 <= year <= 2100:
                return date(year, 12, 31)
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except ValueError:
                continue
        match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%d.%m.%Y").date()
            except ValueError:
                return None
        return None

    @classmethod
    def _load_projects(cls, project_ids: list[uuid.UUID]) -> list[Project]:
        if not project_ids:
            return []
        projects = list(
            db.session.scalars(
                db.select(Project).where(Project.id.in_(project_ids), Project.active_filter())
            )
        )
        if len(projects) != len(set(project_ids)):
            raise ValidationError("Один или несколько проектов не найдены.")
        return projects

    @classmethod
    def _validate_tender_links(
        cls,
        *,
        object_id: uuid.UUID | None,
        projects: list[Project],
        tender_id: uuid.UUID | None = None,
    ) -> None:
        if object_id is None and not projects:
            raise ValidationError("Укажите объект и/или хотя бы один проект.")
        if object_id is not None:
            obj = db.session.scalar(
                db.select(WorkObject).where(WorkObject.id == object_id, WorkObject.active_filter())
            )
            if obj is None:
                raise ValidationError("Выбранный объект не найден.")
        if projects:
            cls._validate_projects_for_tender(projects, tender_id=tender_id)

    @classmethod
    def _validate_projects_for_tender(
        cls,
        projects: list[Project],
        *,
        tender_id: uuid.UUID | None = None,
    ) -> None:
        allowed = {
            ProjectStatus.DRAFT.value,
            ProjectStatus.ACTIVE.value,
            ProjectStatus.IN_TENDER.value,
            ProjectStatus.CANCELLED.value,
        }
        for project in projects:
            if project.object_id is None:
                raise ValidationError(f"У проекта {project.code} не указан объект.")
            if project.status == ProjectStatus.IN_TENDER.value and tender_id is not None:
                # уже в этой заявке — ок при редактировании
                link = db.session.scalar(
                    db.select(TenderProject).where(
                        TenderProject.project_id == project.id,
                        TenderProject.tender_id == tender_id,
                        TenderProject.active_filter(),
                    )
                )
                if link is not None:
                    continue
            if project.status not in allowed or (
                project.status == ProjectStatus.IN_TENDER.value and tender_id is None
            ):
                raise ValidationError(
                    f"Проект {project.code} нельзя включить в заявку (статус: {project.status})."
                )

    @classmethod
    def _sync_project_links(
        cls,
        tender: TenderApplication,
        projects: list[Project],
        user_id: uuid.UUID,
    ) -> None:
        desired = {p.id for p in projects}
        current = {link.project_id: link for link in tender.project_links if link.deleted_at is None}
        for project_id, link in current.items():
            if project_id not in desired:
                link.soft_delete(user_id)
                project = link.project
                if project and project.status == ProjectStatus.IN_TENDER.value:
                    project.status = ProjectStatus.ACTIVE.value
                    if project.work_object and project.work_object.status == WorkObjectStatus.IN_TENDER.value:
                        project.work_object.status = WorkObjectStatus.IN_PROJECT.value
        for project in projects:
            if project.id in current:
                continue
            # Уже есть soft-deleted связь — восстанавливаем (unique без partial index).
            stale = next(
                (
                    link
                    for link in tender.project_links
                    if link.project_id == project.id and link.deleted_at is not None
                ),
                None,
            )
            if stale is not None:
                stale.restore()
                stale.updated_by = user_id
                continue
            db.session.add(
                TenderProject(
                    tender_id=tender.id,
                    project_id=project.id,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )

    @classmethod
    def _apply_status_side_effects(
        cls,
        tender: TenderApplication,
        user_id: uuid.UUID,
        projects: list[Project] | None = None,
    ) -> None:
        if projects is None:
            projects = [
                link.project
                for link in tender.project_links
                if link.deleted_at is None and link.project is not None
            ]
        if tender.status in (
            TenderApplicationStatus.DRAFT.value,
            TenderApplicationStatus.SUBMITTED.value,
            TenderApplicationStatus.WON.value,
        ):
            for project in projects:
                project.status = ProjectStatus.IN_TENDER.value
                project.updated_by = user_id
                if project.work_object:
                    project.work_object.status = WorkObjectStatus.IN_TENDER.value
                    project.work_object.updated_by = user_id
        elif tender.status in (
            TenderApplicationStatus.LOST.value,
            TenderApplicationStatus.CANCELLED.value,
        ):
            for project in projects:
                project.status = ProjectStatus.ACTIVE.value
                project.updated_by = user_id
                if project.work_object:
                    project.work_object.status = WorkObjectStatus.IN_PROJECT.value
                    project.work_object.updated_by = user_id

    @classmethod
    def create(cls, payload: TenderPayload, user_id: uuid.UUID, *, commit: bool = True) -> TenderApplication:
        if not payload.number.strip() or not payload.title.strip():
            raise ValidationError("Номер и название обязательны.")
        exists = db.session.scalar(
            db.select(TenderApplication).where(
                TenderApplication.number == payload.number.strip(),
                TenderApplication.active_filter(),
            )
        )
        if exists is not None:
            raise ValidationError("Заявка на торги с таким номером уже есть.")

        projects = cls._load_projects(payload.project_ids)
        cls._validate_tender_links(
            object_id=payload.object_id,
            projects=projects,
        )

        deadline = cls._normalize(payload.work_deadline)
        tender = TenderApplication(
            number=payload.number.strip(),
            title=payload.title.strip(),
            description=cls._normalize(payload.description),
            status=payload.status or TenderApplicationStatus.DRAFT.value,
            responsible_id=payload.responsible_id,
            object_id=payload.object_id,
            work_deadline=deadline,
            work_deadline_date=cls.parse_deadline_date(deadline),
            published_at=payload.published_at,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(tender)
        db.session.flush()
        cls._sync_project_links(tender, projects, user_id)
        db.session.flush()
        cls._apply_status_side_effects(tender, user_id, projects)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.CREATE.value,
            entity_type=EntityType.TENDER_APPLICATION.value,
            entity_id=tender.id,
            description=f"Создана заявка на торги {tender.number}",
            new_values={"number": tender.number, "status": tender.status},
        )
        if commit:
            db.session.commit()
        return tender

    @classmethod
    def update(cls, tender: TenderApplication, payload: TenderPayload, user_id: uuid.UUID) -> TenderApplication:
        if tender.status not in (
            TenderApplicationStatus.DRAFT.value,
            TenderApplicationStatus.SUBMITTED.value,
        ):
            # состав меняем только в черновике/переданной; статус можно обновлять отдельно
            pass
        projects = cls._load_projects(payload.project_ids)
        cls._validate_tender_links(
            object_id=payload.object_id,
            projects=projects,
            tender_id=tender.id,
        )
        tender.number = payload.number.strip()
        tender.title = payload.title.strip()
        tender.description = cls._normalize(payload.description)
        previous = tender.status
        tender.status = payload.status
        tender.responsible_id = payload.responsible_id
        tender.object_id = payload.object_id
        tender.work_deadline = cls._normalize(payload.work_deadline)
        tender.work_deadline_date = cls.parse_deadline_date(tender.work_deadline)
        tender.published_at = payload.published_at
        tender.updated_by = user_id
        if previous in (
            TenderApplicationStatus.DRAFT.value,
            TenderApplicationStatus.SUBMITTED.value,
        ) or tender.status == TenderApplicationStatus.DRAFT.value:
            cls._sync_project_links(tender, projects, user_id)
        db.session.flush()
        cls._apply_status_side_effects(tender, user_id, projects)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.TENDER_APPLICATION.value,
            entity_id=tender.id,
            description=f"Обновлена заявка на торги {tender.number}",
        )
        db.session.commit()
        return tender

    @classmethod
    def set_status(cls, tender: TenderApplication, status: str, user_id: uuid.UUID) -> TenderApplication:
        allowed = {s.value for s in TenderApplicationStatus}
        if status not in allowed:
            raise ValidationError("Некорректный статус.")
        tender.status = status
        tender.updated_by = user_id
        projects = [
            link.project
            for link in tender.project_links
            if link.deleted_at is None and link.project is not None
        ]
        cls._apply_status_side_effects(tender, user_id, projects)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.STATUS_CHANGE.value,
            entity_type=EntityType.TENDER_APPLICATION.value,
            entity_id=tender.id,
            description=f"Статус заявки на торги {tender.number}: {status}",
        )
        db.session.commit()
        return tender

    @classmethod
    def add_document(
        cls,
        tender: TenderApplication,
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
    ) -> TenderDocument:
        if not title.strip():
            raise ValidationError("Название документа обязательно.")
        doc = TenderDocument(
            tender_id=tender.id,
            title=title.strip(),
            document_type=document_type,
            document_number=cls._normalize(document_number),
            document_date=document_date,
            description=cls._normalize(description),
            file_name=file_name,
            mime_type=mime_type,
            storage_key=storage_key,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(doc)
        AuditService.log(
            user_id=user_id,
            action=AuditAction.UPDATE.value,
            entity_type=EntityType.TENDER_APPLICATION.value,
            entity_id=tender.id,
            description=f"Документ к заявке на торги: {title}",
        )
        db.session.commit()
        return doc

    @classmethod
    def linked_project_documents(cls, tender: TenderApplication) -> list[Any]:
        docs = []
        for link in tender.project_links:
            if link.deleted_at is not None or link.project is None:
                continue
            for doc in link.project.documents:
                if doc.deleted_at is None:
                    docs.append(doc)
        return docs
