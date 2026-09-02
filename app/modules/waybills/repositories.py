"""Репозиторий путевых листов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import joinedload, noload, selectinload

from app.core.numbering import next_prefixed_number
from app.extensions import db
from app.models.waybills.waybill import Waybill
from app.models.waybills.waybill_stop import WaybillStop
from app.modules.requests.repositories import RequestRepository


@dataclass
class WaybillFilter:
    q: str = ""
    status: str = ""
    sort_by: str = "work_date"
    sort_dir: str = "desc"


class WaybillRepository:
    SORT_FIELDS = {
        "created_at": Waybill.created_at,
        "work_date": Waybill.work_date,
        "number": Waybill.number,
        "status": Waybill.status,
    }

    @staticmethod
    def get_by_id(waybill_id: uuid.UUID | str) -> Waybill | None:
        if isinstance(waybill_id, str):
            try:
                waybill_id = uuid.UUID(waybill_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Waybill)
            .options(
                joinedload(Waybill.master),
                selectinload(Waybill.stops).joinedload(WaybillStop.request),
                selectinload(Waybill.stops).joinedload(WaybillStop.defect),
                selectinload(Waybill.members),
            )
            .where(Waybill.id == waybill_id, Waybill.active_filter())
        )

    @staticmethod
    def next_number() -> str:
        return next_prefixed_number(Waybill, "PL")

    @staticmethod
    def get_masters():
        return RequestRepository.get_masters()

    @classmethod
    def paginated_list(cls, filters: WaybillFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(Waybill)
            .where(Waybill.active_filter())
            .options(joinedload(Waybill.master), noload(Waybill.stops), noload(Waybill.history), noload(Waybill.members))
        )
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(or_(Waybill.number.ilike(q), Waybill.comment.ilike(q)))
        if filters.status:
            stmt = stmt.where(Waybill.status == filters.status)
        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Waybill.work_date)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, Waybill.created_at.desc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
