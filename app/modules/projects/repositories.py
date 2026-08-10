"""Репозитории модуля проектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models.auth.user import User
from app.models.enums import ProjectMemberRole
from app.models.projects.project import Project
from app.models.projects.project_member import ProjectMember


@dataclass
class ProjectFilter:
    q: str = ""
    status: str = ""
    responsible_id: str = ""
    executor_id: str = ""
    date_from: str = ""
    date_to: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class ProjectRepository:
    """Чтение и запись проектов."""

    SORT_FIELDS = {
        "created_at": Project.created_at,
        "updated_at": Project.updated_at,
        "name": Project.name,
        "code": Project.code,
        "status": Project.status,
        "progress_percent": Project.progress_percent,
        "start_date": Project.start_date,
        "end_date": Project.end_date,
    }

    @staticmethod
    def get_by_id(project_id: uuid.UUID | str) -> Project | None:
        if isinstance(project_id, str):
            try:
                project_id = uuid.UUID(project_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Project).where(Project.id == project_id, Project.active_filter())
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
    def next_code() -> str:
        from datetime import datetime

        year = datetime.now().year
        prefix = f"PRJ-{year}-"
        last = db.session.scalar(
            db.select(Project.code)
            .where(Project.code.ilike(f"{prefix}%"), Project.active_filter())
            .order_by(Project.code.desc())
            .limit(1)
        )
        if not last:
            return f"{prefix}001"
        try:
            seq = int(last.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
        return f"{prefix}{seq:03d}"

    @classmethod
    def paginated_list(cls, filters: ProjectFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(Project)
            .where(Project.active_filter())
            .options(
                joinedload(Project.manager),
                selectinload(Project.members).joinedload(ProjectMember.user),
            )
        )
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    Project.code.ilike(q),
                    Project.name.ilike(q),
                    Project.description.ilike(q),
                )
            )

        if filters.status:
            stmt = stmt.where(Project.status == filters.status)

        if filters.responsible_id:
            try:
                stmt = stmt.where(Project.manager_id == uuid.UUID(filters.responsible_id))
            except ValueError:
                pass

        if filters.executor_id:
            try:
                executor_uuid = uuid.UUID(filters.executor_id)
                stmt = stmt.where(
                    Project.id.in_(
                        db.select(ProjectMember.project_id).where(
                            ProjectMember.user_id == executor_uuid,
                            ProjectMember.role_in_project == ProjectMemberRole.EXECUTOR.value,
                            ProjectMember.active_filter(),
                        )
                    )
                )
            except ValueError:
                pass

        if filters.date_from:
            try:
                stmt = stmt.where(Project.start_date >= date.fromisoformat(filters.date_from))
            except ValueError:
                pass

        if filters.date_to:
            try:
                stmt = stmt.where(Project.end_date <= date.fromisoformat(filters.date_to))
            except ValueError:
                pass

        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Project.created_at)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, Project.created_at.desc())

        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_executor_ids(project: Project) -> list[uuid.UUID]:
        return [
            member.user_id
            for member in project.active_members
            if member.role_in_project == ProjectMemberRole.EXECUTOR.value
        ]
