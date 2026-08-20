"""Выборки обращений."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.extensions import db
from app.models.inquiries.inquiry import Inquiry


@dataclass
class InquiryFilter:
    q: str = ""
    status: str = ""


class InquiryRepository:
    @staticmethod
    def get_by_id(item_id: uuid.UUID) -> Inquiry | None:
        return db.session.scalar(
            db.select(Inquiry).where(Inquiry.id == item_id, Inquiry.deleted_at.is_(None))
        )

    @classmethod
    def paginated_list(cls, filters: InquiryFilter, page: int = 1, per_page: int = 30):
        stmt = db.select(Inquiry).where(Inquiry.deleted_at.is_(None))
        q = (filters.q or "").strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                db.or_(
                    Inquiry.subject.ilike(like),
                    Inquiry.from_email.ilike(like),
                    Inquiry.from_name.ilike(like),
                    Inquiry.body_text.ilike(like),
                )
            )
        if filters.status:
            stmt = stmt.where(Inquiry.status == filters.status)
        stmt = stmt.order_by(Inquiry.received_at.desc(), Inquiry.created_at.desc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def unread_count() -> int:
        return int(
            db.session.scalar(
                db.select(db.func.count())
                .select_from(Inquiry)
                .where(Inquiry.deleted_at.is_(None), Inquiry.status == "new")
            )
            or 0
        )
