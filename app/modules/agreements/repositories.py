"""Выборки договоров на опорах."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import noload, selectinload

from app.extensions import db
from app.models.agreements.pole_agreement import PoleAgreement
from app.models.agreements.pole_agreement_site import PoleAgreementSite


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
            .options(noload(PoleAgreement.sites))
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
        pagination = db.paginate(stmt, page=page, per_page=per_page, error_out=False)
        ids = [item.id for item in pagination.items]
        counts: dict = {}
        if ids:
            counts = dict(
                db.session.execute(
                    db.select(PoleAgreementSite.agreement_id, func.count())
                    .where(
                        PoleAgreementSite.agreement_id.in_(ids),
                        PoleAgreementSite.deleted_at.is_(None),
                    )
                    .group_by(PoleAgreementSite.agreement_id)
                ).all()
            )
        for item in pagination.items:
            item.sites_count = counts.get(item.id, 0)
        return pagination
