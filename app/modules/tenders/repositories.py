"""Репозиторий заявок на торги."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import joinedload, load_only, noload, selectinload

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import ProjectStatus
from app.models.projects.project import Project
from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_project import TenderProject
from app.models.work_objects.work_object import WorkObject


@dataclass
class TenderFilter:
    q: str = ""
    status: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


def _user_name_only():
    return (
        load_only(User.id, User.full_name),
        noload(User.user_roles),
        noload(User.login_logs),
    )


class TenderRepository:
    SORT_FIELDS = {
        "created_at": TenderApplication.created_at,
        "updated_at": TenderApplication.updated_at,
        "number": TenderApplication.number,
        "title": TenderApplication.title,
        "status": TenderApplication.status,
        "work_deadline": TenderApplication.work_deadline,
    }

    @staticmethod
    def get_by_id(tender_id: uuid.UUID | str) -> TenderApplication | None:
        if isinstance(tender_id, str):
            try:
                tender_id = uuid.UUID(tender_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(TenderApplication)
            .where(TenderApplication.id == tender_id, TenderApplication.active_filter())
            .options(
                selectinload(TenderApplication.project_links)
                .joinedload(TenderProject.project)
                .options(
                    joinedload(Project.work_object),
                    selectinload(Project.documents),
                    noload(Project.members),
                    noload(Project.history),
                    noload(Project.requests),
                    noload(Project.contracts),
                ),
                selectinload(TenderApplication.documents),
                joinedload(TenderApplication.responsible).options(
                    load_only(User.id, User.full_name),
                    noload(User.login_logs),
                ),
                joinedload(TenderApplication.work_object),
                noload(TenderApplication.contracts),
            )
        )

    @staticmethod
    def get_users() -> list[User]:
        return list(
            db.session.scalars(
                db.select(User)
                .options(*_user_name_only())
                .where(User.active_filter(), User.is_active.is_(True), User.is_blocked.is_(False))
                .order_by(User.full_name.asc())
            )
        )

    @staticmethod
    def next_number() -> str:
        from datetime import datetime

        year = datetime.now().year
        prefix = f"ТРГ-{year}-"
        last = db.session.scalar(
            db.select(TenderApplication.number)
            .where(TenderApplication.number.ilike(f"{prefix}%"), TenderApplication.active_filter())
            .order_by(TenderApplication.number.desc())
            .limit(1)
        )
        if not last:
            return f"{prefix}001"
        try:
            seq = int(last.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
        return f"{prefix}{seq:03d}"

    @staticmethod
    def selectable_projects(
        extra_ids: list[uuid.UUID] | None = None,
        q: str = "",
        limit: int = 40,
    ) -> list[Project]:
        allowed = {
            ProjectStatus.DRAFT.value,
            ProjectStatus.ACTIVE.value,
            ProjectStatus.CANCELLED.value,
        }
        extras = [item_id for item_id in extra_ids or [] if item_id]
        options = (
            load_only(Project.id, Project.code, Project.name, Project.status, Project.object_id),
            joinedload(Project.work_object).load_only(
                WorkObject.id, WorkObject.address, WorkObject.name
            ),
            noload(Project.members),
            noload(Project.history),
            noload(Project.documents),
            noload(Project.requests),
            noload(Project.contracts),
        )
        stmt = (
            db.select(Project)
            .where(Project.active_filter(), Project.status.in_(allowed))
            .options(*options)
            .order_by(Project.code.asc())
        )
        if q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Project.code.ilike(like), Project.name.ilike(like)))
        projects = list(db.session.scalars(stmt.limit(limit)).unique())
        existing_ids = {p.id for p in projects}
        missing = [item_id for item_id in extras if item_id not in existing_ids]
        if missing:
            more = list(
                db.session.scalars(
                    db.select(Project)
                    .where(Project.id.in_(missing), Project.active_filter())
                    .options(*options)
                ).unique()
            )
            projects.extend(more)
        return projects

    @staticmethod
    def project_choice_label(project: Project) -> str:
        label = f"{project.code} — {project.name}"
        if project.work_object:
            extra = (project.work_object.address or project.work_object.name or "").strip()
            if extra:
                label = f"{label} ({extra[:80]})"
        return label

    @classmethod
    def paginated_list(cls, filters: TenderFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(TenderApplication)
            .where(TenderApplication.active_filter())
            .options(
                load_only(
                    TenderApplication.id,
                    TenderApplication.number,
                    TenderApplication.title,
                    TenderApplication.status,
                    TenderApplication.work_deadline,
                    TenderApplication.object_id,
                ),
                joinedload(TenderApplication.work_object).options(
                    load_only(
                        WorkObject.id,
                        WorkObject.address,
                        WorkObject.name,
                    ),
                    noload(WorkObject.projects),
                ),
                noload(TenderApplication.project_links),
                noload(TenderApplication.documents),
                noload(TenderApplication.responsible),
                noload(TenderApplication.contracts),
            )
        )
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    TenderApplication.number.ilike(q),
                    TenderApplication.title.ilike(q),
                    TenderApplication.description.ilike(q),
                )
            )
        if filters.status:
            stmt = stmt.where(TenderApplication.status == filters.status)
        sort_col = cls.SORT_FIELDS.get(filters.sort_by, TenderApplication.created_at)
        stmt = stmt.order_by(sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
