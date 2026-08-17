"""Репозиторий объектов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import exists, or_
from sqlalchemy.orm import load_only, noload

from app.extensions import db
from app.models.tenders.tender_application import TenderApplication
from app.models.work_objects.work_object import WorkObject

CHOICE_LIMIT = 40


def _parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _unique_uuids(*groups: list[uuid.UUID] | uuid.UUID | None) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for group in groups:
        values = group if isinstance(group, list) else [group]
        for value in values:
            if value and value not in result:
                result.append(value)
    return result


@dataclass
class ObjectFilter:
    q: str = ""
    statuses: list[str] = field(default_factory=list)
    object_kinds: list[str] = field(default_factory=list)
    plan_year: str = ""
    contractor_name: str = ""
    deadline_from: str = ""
    deadline_to: str = ""
    sort_by: str = "created_at"
    sort_dir: str = "desc"
    # совместимость со старым одиночным фильтром
    status: str = ""
    object_kind: str = ""


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
    def list_choices(
        q: str = "",
        limit: int = CHOICE_LIMIT,
        extra_ids: list[uuid.UUID] | None = None,
        *,
        free_only: bool = False,
        current_id: uuid.UUID | None = None,
    ) -> list[WorkObject]:
        """Короткий список для select: не грузим весь справочник объектов."""
        from app.models.enums import WorkObjectStatus

        extras = _unique_uuids(extra_ids, current_id)
        stmt = (
            db.select(WorkObject)
            .options(
                load_only(WorkObject.id, WorkObject.address, WorkObject.name, WorkObject.status),
                noload(WorkObject.projects),
            )
            .where(WorkObject.active_filter())
        )
        if free_only:
            if extras:
                stmt = stmt.where(
                    (WorkObject.status == WorkObjectStatus.FREE.value) | (WorkObject.id.in_(extras))
                )
            else:
                stmt = stmt.where(WorkObject.status == WorkObjectStatus.FREE.value)
        if q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(WorkObject.address.ilike(like), WorkObject.name.ilike(like)))
        items = list(
            db.session.scalars(
                stmt.order_by(WorkObject.address.asc().nulls_last(), WorkObject.name.asc()).limit(limit)
            )
        )
        missing = [item_id for item_id in extras if item_id not in {item.id for item in items}]
        if missing:
            items.extend(
                db.session.scalars(
                    db.select(WorkObject)
                    .options(
                        load_only(
                            WorkObject.id, WorkObject.address, WorkObject.name, WorkObject.status
                        ),
                        noload(WorkObject.projects),
                    )
                    .where(WorkObject.id.in_(missing), WorkObject.active_filter())
                )
            )
        return items

    @staticmethod
    def list_free_or_current(
        current_id: uuid.UUID | None = None,
        q: str = "",
        limit: int = CHOICE_LIMIT,
        extra_ids: list[uuid.UUID] | None = None,
    ) -> list[WorkObject]:
        return ObjectRepository.list_choices(
            q=q,
            limit=limit,
            extra_ids=extra_ids,
            free_only=True,
            current_id=current_id,
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
                )
            )
        statuses = [item for item in (filters.statuses or []) if item]
        if not statuses and filters.status:
            statuses = [filters.status]
        if statuses:
            stmt = stmt.where(WorkObject.status.in_(statuses))
        kinds = [item for item in (filters.object_kinds or []) if item]
        if not kinds and filters.object_kind:
            kinds = [filters.object_kind]
        if kinds:
            stmt = stmt.where(WorkObject.object_kind.in_(kinds))
        if filters.plan_year and filters.plan_year.isdigit():
            stmt = stmt.where(WorkObject.plan_year == int(filters.plan_year))
        if filters.contractor_name.strip():
            stmt = stmt.where(
                WorkObject.contractor_name.ilike(f"%{filters.contractor_name.strip()}%")
            )
        deadline_from = _parse_iso_date(filters.deadline_from)
        deadline_to = _parse_iso_date(filters.deadline_to)
        if deadline_from or deadline_to:
            tender_exists = (
                db.select(TenderApplication.id)
                .where(
                    TenderApplication.object_id == WorkObject.id,
                    TenderApplication.active_filter(),
                    TenderApplication.work_deadline_date.is_not(None),
                )
            )
            if deadline_from:
                tender_exists = tender_exists.where(
                    TenderApplication.work_deadline_date >= deadline_from
                )
            if deadline_to:
                tender_exists = tender_exists.where(
                    TenderApplication.work_deadline_date <= deadline_to
                )
            stmt = stmt.where(exists(tender_exists))

        sort_col = cls.SORT_FIELDS.get(filters.sort_by, WorkObject.created_at)
        stmt = stmt.order_by(sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
