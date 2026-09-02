"""Репозиторий дефектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import contains_eager, joinedload, load_only, noload

from app.core.numbering import next_prefixed_number
from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_status import DefectStatus
from app.modules.requests.repositories import RequestRepository


@dataclass
class DefectFilter:
    q: str = ""
    district: str = ""
    status_id: str = ""
    category_id: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class DefectRepository:
    SORT_FIELDS = {
        "created_at": Defect.created_at,
        "updated_at": Defect.updated_at,
        "number": Defect.number,
        "address": Defect.address,
        "status_id": Defect.status_id,
    }

    @staticmethod
    def get_by_id(defect_id: uuid.UUID | str) -> Defect | None:
        if isinstance(defect_id, str):
            try:
                defect_id = uuid.UUID(defect_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Defect)
            .options(
                joinedload(Defect.status),
                joinedload(Defect.category),
                joinedload(Defect.responsible),
            )
            .where(Defect.id == defect_id, Defect.active_filter())
        )

    @staticmethod
    def get_statuses() -> list[DefectStatus]:
        return list(
            db.session.scalars(
                db.select(DefectStatus)
                .where(DefectStatus.active_filter(), DefectStatus.is_active.is_(True))
                .order_by(DefectStatus.sort_order.asc())
            )
        )

    @staticmethod
    def get_status_by_code(code: str) -> DefectStatus | None:
        return db.session.scalar(
            db.select(DefectStatus).where(
                DefectStatus.code == code,
                DefectStatus.active_filter(),
                DefectStatus.is_active.is_(True),
            )
        )

    @staticmethod
    def get_categories() -> list[DefectCategory]:
        return list(
            db.session.scalars(
                db.select(DefectCategory)
                .where(DefectCategory.active_filter(), DefectCategory.is_active.is_(True))
                .order_by(DefectCategory.sort_order.asc())
            )
        )

    @staticmethod
    def next_number() -> str:
        return next_prefixed_number(Defect, "DF")

    @classmethod
    def paginated_list(cls, filters: DefectFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(Defect)
            .where(Defect.active_filter())
            .join(Defect.status)
            .options(
                load_only(
                    Defect.id,
                    Defect.number,
                    Defect.address,
                    Defect.district,
                    Defect.description,
                    Defect.status_id,
                    Defect.category_id,
                    Defect.created_at,
                    Defect.responsible_id,
                ),
                contains_eager(Defect.status),
                joinedload(Defect.category),
                noload(Defect.history),
            )
        )
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    Defect.number.ilike(q),
                    Defect.address.ilike(q),
                    Defect.description.ilike(q),
                )
            )
        if filters.district:
            stmt = stmt.where(Defect.district.ilike(f"%{filters.district.strip()}%"))
        if filters.status_id:
            try:
                stmt = stmt.where(Defect.status_id == uuid.UUID(filters.status_id))
            except ValueError:
                pass
        if filters.category_id:
            try:
                stmt = stmt.where(Defect.category_id == uuid.UUID(filters.category_id))
            except ValueError:
                pass
        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Defect.created_at)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, Defect.created_at.desc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def get_masters():
        return RequestRepository.get_masters()

    @staticmethod
    def map_points(*, limit: int = 500) -> list[dict]:
        rows = db.session.scalars(
            db.select(Defect)
            .options(load_only(Defect.id, Defect.number, Defect.address, Defect.latitude, Defect.longitude, Defect.status_id))
            .join(DefectStatus, Defect.status_id == DefectStatus.id)
            .where(
                Defect.active_filter(),
                Defect.latitude.isnot(None),
                Defect.longitude.isnot(None),
            )
            .limit(limit)
        )
        points = []
        for item in rows:
            points.append(
                {
                    "id": str(item.id),
                    "type": "defect",
                    "number": item.number,
                    "address": item.address,
                    "lat": float(item.latitude),
                    "lng": float(item.longitude),
                    "url": f"/defects/{item.id}",
                }
            )
        return points
