"""Выборки договоров на опорах."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.agreements.pole_agreement import PoleAgreement


@dataclass
class AgreementFilter:
    q: str = ""


class AgreementRepository:
    @staticmethod
    def get_by_id(item_id: uuid.UUID) -> PoleAgreement | None:
        return db.session.scalar(
            db.select(PoleAgreement)
            .options(selectinload(PoleAgreement.sites))
            .where(
                PoleAgreement.id == item_id,
                PoleAgreement.active_filter(),
            )
        )

    @classmethod
    def paginated_list(cls, filters: AgreementFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(PoleAgreement)
            .options(selectinload(PoleAgreement.sites))
            .where(PoleAgreement.active_filter())
        )
        q = (filters.q or "").strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                db.or_(
                    PoleAgreement.title.ilike(like),
                    PoleAgreement.number.ilike(like),
                    PoleAgreement.customer_name.ilike(like),
                )
            )
        stmt = stmt.order_by(PoleAgreement.created_at.desc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
