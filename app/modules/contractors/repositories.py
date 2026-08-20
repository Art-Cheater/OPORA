"""Репозиторий подрядчиков."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models.contractors.contractor import Contractor
from app.models.contracts.contract_contractor import ContractContractor


@dataclass
class ContractorFilter:
    q: str = ""
    sort_by: str = "name"
    sort_dir: str = "asc"


class ContractorRepository:
    SORT_FIELDS = {
        "name": Contractor.name,
        "inn": Contractor.inn,
        "created_at": Contractor.created_at,
        "updated_at": Contractor.updated_at,
    }

    @staticmethod
    def get_by_id(contractor_id: uuid.UUID | str) -> Contractor | None:
        if isinstance(contractor_id, str):
            try:
                contractor_id = uuid.UUID(contractor_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Contractor)
            .options(selectinload(Contractor.contract_links).selectinload(ContractContractor.contract))
            .where(Contractor.id == contractor_id, Contractor.active_filter())
        )

    @classmethod
    def get_by_inn(cls, inn: str) -> Contractor | None:
        inn = (inn or "").strip()
        if not inn:
            return None
        return db.session.scalar(
            db.select(Contractor).where(Contractor.inn == inn, Contractor.active_filter())
        )

    @classmethod
    def paginated_list(cls, filters: ContractorFilter, page: int = 1, per_page: int = 20):
        stmt = db.select(Contractor).where(Contractor.active_filter())
        q = (filters.q or "").strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Contractor.name.ilike(like),
                    Contractor.inn.ilike(like),
                    Contractor.kpp.ilike(like),
                    Contractor.address.ilike(like),
                )
            )
        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Contractor.name)
        if (filters.sort_dir or "asc").lower() == "desc":
            stmt = stmt.order_by(sort_col.desc())
        else:
            stmt = stmt.order_by(sort_col.asc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
