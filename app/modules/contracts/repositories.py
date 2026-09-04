"""Репозитории модуля контрактов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import joinedload, load_only, noload, selectinload

from app.extensions import db
from app.models.auth.user import User
from app.models.contracts.contract import Contract
from app.models.contracts.contract_object import ContractObject
from app.models.contracts.contract_project import ContractProject


@dataclass
class ContractFilter:
    q: str = ""
    contract_type: str = ""
    status: str = ""
    responsible_id: str = ""
    contract_date: str = ""
    end_date_from: str = ""
    end_date_to: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class ContractRepository:
    """Чтение и запись контрактов."""

    SORT_FIELDS = {
        "created_at": Contract.created_at,
        "updated_at": Contract.updated_at,
        "number": Contract.number,
        "title": Contract.title,
        "status": Contract.status,
        "contract_type": Contract.contract_type,
        "contract_date": Contract.contract_date,
        "end_date": Contract.end_date,
        "contractor_name": Contract.contractor_name,
        "amount": Contract.amount,
    }

    @staticmethod
    def get_by_id(contract_id: uuid.UUID | str) -> Contract | None:
        if isinstance(contract_id, str):
            try:
                contract_id = uuid.UUID(contract_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Contract)
            .where(Contract.id == contract_id, Contract.active_filter())
            .options(
                selectinload(Contract.object_links).joinedload(ContractObject.work_object),
                selectinload(Contract.project_links).joinedload(ContractProject.project),
                selectinload(Contract.history),
                selectinload(Contract.documents),
                joinedload(Contract.responsible).options(
                    load_only(User.id, User.full_name),
                    noload(User.login_logs),
                ),
                joinedload(Contract.project),
                joinedload(Contract.tender_application),
            )
        )

    @staticmethod
    def get_users():
        from app.modules.auth.repositories import UserRepository

        return UserRepository.list_active_names()

    @staticmethod
    def next_number() -> str:
        from datetime import datetime

        year = datetime.now().year
        prefix = f"CTR-{year}-"
        last = db.session.scalar(
            db.select(Contract.number)
            .where(Contract.number.ilike(f"{prefix}%"), Contract.active_filter())
            .order_by(Contract.number.desc())
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
    def paginated_list(cls, filters: ContractFilter, page: int = 1, per_page: int = 20):
        stmt = (
            db.select(Contract)
            .where(Contract.active_filter())
            .options(
                load_only(
                    Contract.id,
                    Contract.number,
                    Contract.title,
                    Contract.description,
                    Contract.contract_type,
                    Contract.status,
                    Contract.contractor_name,
                    Contract.amount,
                    Contract.currency,
                    Contract.contract_date,
                    Contract.end_date,
                    Contract.updated_at,
                    Contract.responsible_id,
                ),
                joinedload(Contract.responsible).options(
                    load_only(User.id, User.full_name),
                    noload(User.user_roles),
                    noload(User.login_logs),
                ),
                noload(Contract.object_links),
                noload(Contract.history),
                noload(Contract.documents),
                noload(Contract.project),
                noload(Contract.tender_application),
            )
        )
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    Contract.number.ilike(q),
                    Contract.title.ilike(q),
                    Contract.description.ilike(q),
                    Contract.contractor_name.ilike(q),
                )
            )

        if filters.contract_type:
            stmt = stmt.where(Contract.contract_type == filters.contract_type)

        if filters.status:
            stmt = stmt.where(Contract.status == filters.status)

        if filters.responsible_id:
            try:
                stmt = stmt.where(Contract.responsible_id == uuid.UUID(filters.responsible_id))
            except ValueError:
                pass

        if filters.contract_date:
            try:
                stmt = stmt.where(
                    Contract.contract_date == date.fromisoformat(filters.contract_date)
                )
            except ValueError:
                pass

        if filters.end_date_from:
            try:
                stmt = stmt.where(Contract.end_date >= date.fromisoformat(filters.end_date_from))
            except ValueError:
                pass

        if filters.end_date_to:
            try:
                stmt = stmt.where(Contract.end_date <= date.fromisoformat(filters.end_date_to))
            except ValueError:
                pass

        sort_col = cls.SORT_FIELDS.get(filters.sort_by, Contract.created_at)
        sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
        stmt = stmt.order_by(sort_expr, Contract.created_at.desc())

        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
