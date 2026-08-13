"""Репозиторий объектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import load_only, noload

from app.extensions import db
from app.models.work_objects.work_object import WorkObject


@dataclass
class ObjectFilter:
    q: str = ""
    status: str = ""
    object_kind: str = ""
    plan_year: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class ObjectRepository:
    SORT_FIELDS = {
        "created_at": WorkObject.created_at,
        "updated_at": WorkObject.updated_at,
        "name": WorkObject.name,
        "address": WorkObject.address,
        "status": WorkObject.status,
        "plan_year": WorkObject.plan_year,
        "contractor_name": WorkObject.contractor_name,
        "work_deadline": WorkObject.work_deadline,
        "contract_number": WorkObject.contract_number,
        "contract_date": WorkObject.contract_date,
        "object_kind": WorkObject.object_kind,
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
    def list_all() -> list[WorkObject]:
        return list(
            db.session.scalars(
                db.select(WorkObject)
                .where(WorkObject.active_filter())
                .order_by(WorkObject.address.asc().nulls_last(), WorkObject.name.asc())
            )
        )

    @staticmethod
    def list_choices() -> list[WorkObject]:
        """Лёгкий список для select: только id/address/name."""
        return list(
            db.session.scalars(
                db.select(WorkObject)
                .options(load_only(WorkObject.id, WorkObject.address, WorkObject.name))
                .where(WorkObject.active_filter())
                .order_by(WorkObject.address.asc().nulls_last(), WorkObject.name.asc())
            )
        )

    @staticmethod
    def list_free_or_current(current_id: uuid.UUID | None = None) -> list[WorkObject]:
        from app.models.enums import WorkObjectStatus

        stmt = (
            db.select(WorkObject)
            .options(load_only(WorkObject.id, WorkObject.address, WorkObject.name, WorkObject.status))
            .where(WorkObject.active_filter())
        )
        if current_id is not None:
            stmt = stmt.where(
                (WorkObject.status == WorkObjectStatus.FREE.value) | (WorkObject.id == current_id)
            )
        else:
            stmt = stmt.where(WorkObject.status == WorkObjectStatus.FREE.value)
        return list(
            db.session.scalars(
                stmt.order_by(WorkObject.address.asc().nulls_last(), WorkObject.name.asc())
            )
        )

    @staticmethod
    def label_for_select(obj: WorkObject) -> str:
        addr = (obj.address or obj.name or "").strip()
        return (addr[:120] if addr else str(obj.id))


    @classmethod
    def paginated_list(cls, filters: ObjectFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(WorkObject)
            .where(WorkObject.active_filter())
            .options(
                load_only(
                    WorkObject.id,
                    WorkObject.name,
                    WorkObject.address,
                    WorkObject.object_kind,
                    WorkObject.work_deadline,
                    WorkObject.contract_number,
                    WorkObject.contract_date,
                    WorkObject.contractor_name,
                    WorkObject.status,
                    WorkObject.plan_year,
                    WorkObject.source_sheet,
                ),
                noload(WorkObject.projects),
            )
        )
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    WorkObject.name.ilike(q),
                    WorkObject.address.ilike(q),
                    WorkObject.contractor_name.ilike(q),
                    WorkObject.contract_number.ilike(q),
                    WorkObject.court_decision_number.ilike(q),
                    WorkObject.notes.ilike(q),
                )
            )
        if filters.status:
            stmt = stmt.where(WorkObject.status == filters.status)
        if filters.object_kind:
            stmt = stmt.where(WorkObject.object_kind == filters.object_kind)
        if filters.plan_year and filters.plan_year.isdigit():
            stmt = stmt.where(WorkObject.plan_year == int(filters.plan_year))

        sort_col = cls.SORT_FIELDS.get(filters.sort_by, WorkObject.created_at)
        stmt = stmt.order_by(sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
