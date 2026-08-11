"""Репозиторий объектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_

from app.extensions import db
from app.models.work_objects.work_object import WorkObject


@dataclass
class ObjectFilter:
    q: str = ""
    status: str = ""
    plan_year: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class ObjectRepository:
    SORT_FIELDS = {
        "created_at": WorkObject.created_at,
        "updated_at": WorkObject.updated_at,
        "name": WorkObject.name,
        "status": WorkObject.status,
        "plan_year": WorkObject.plan_year,
    }

    @staticmethod
    def get_by_id(object_id: uuid.UUID | str) -> WorkObject | None:
        if isinstance(object_id, str):
            try:
                object_id = uuid.UUID(object_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(WorkObject).where(WorkObject.id == object_id, WorkObject.active_filter())
        )

    @staticmethod
    def list_free_or_current(current_id: uuid.UUID | None = None) -> list[WorkObject]:
        from app.models.enums import WorkObjectStatus

        stmt = db.select(WorkObject).where(WorkObject.active_filter())
        if current_id is not None:
            stmt = stmt.where(
                (WorkObject.status == WorkObjectStatus.FREE.value) | (WorkObject.id == current_id)
            )
        else:
            stmt = stmt.where(WorkObject.status == WorkObjectStatus.FREE.value)
        return list(db.session.scalars(stmt.order_by(WorkObject.name.asc())))

    @classmethod
    def paginated_list(cls, filters: ObjectFilter, page: int = 1, per_page: int = 20):
        stmt = db.select(WorkObject).where(WorkObject.active_filter())
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    WorkObject.name.ilike(q),
                    WorkObject.address.ilike(q),
                    WorkObject.notes.ilike(q),
                )
            )
        if filters.status:
            stmt = stmt.where(WorkObject.status == filters.status)
        if filters.plan_year and filters.plan_year.isdigit():
            stmt = stmt.where(WorkObject.plan_year == int(filters.plan_year))

        sort_col = cls.SORT_FIELDS.get(filters.sort_by, WorkObject.created_at)
        stmt = stmt.order_by(sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
