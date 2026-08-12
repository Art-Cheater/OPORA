"""Репозиторий заявок на торги."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import ProjectStatus
from app.models.projects.project import Project
from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_project import TenderProject


@dataclass
class TenderFilter:
    q: str = ""
    status: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class TenderRepository:
    SORT_FIELDS = {
        "created_at": TenderApplication.created_at,
        "updated_at": TenderApplication.updated_at,
        "number": TenderApplication.number,
        "title": TenderApplication.title,
        "status": TenderApplication.status,
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
                selectinload(TenderApplication.project_links).joinedload(TenderProject.project).joinedload(
                    Project.work_object
                ),
                selectinload(TenderApplication.documents),
                joinedload(TenderApplication.responsible),
                joinedload(TenderApplication.work_object),
            )
        )

    @staticmethod
    def get_users() -> list[User]:
        return list(
            db.session.scalars(
                db.select(User)
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
    def selectable_projects(extra_ids: list[uuid.UUID] | None = None) -> list[Project]:
        allowed = {
            ProjectStatus.DRAFT.value,
            ProjectStatus.ACTIVE.value,
            ProjectStatus.CANCELLED.value,
        }
        stmt = (
            db.select(Project)
            .where(Project.active_filter(), Project.status.in_(allowed))
            .options(joinedload(Project.work_object))
            .order_by(Project.code.asc())
        )
        projects = list(db.session.scalars(stmt).unique())
        if extra_ids:
            existing_ids = {p.id for p in projects}
            missing = [i for i in extra_ids if i not in existing_ids]
            if missing:
                more = list(
                    db.session.scalars(
                        db.select(Project)
                        .where(Project.id.in_(missing), Project.active_filter())
                        .options(joinedload(Project.work_object))
                    ).unique()
                )
                projects.extend(more)
        return projects

    @classmethod
    def paginated_list(cls, filters: TenderFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(TenderApplication)
            .where(TenderApplication.active_filter())
            .options(
                selectinload(TenderApplication.project_links).joinedload(TenderProject.project),
                joinedload(TenderApplication.responsible),
                joinedload(TenderApplication.work_object),
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
