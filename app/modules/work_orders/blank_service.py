"""Сохранение бланка-распоряжения и ссылка на него с карточки заявки или дефекта."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.auth.user import User
from app.models.defects.defect import Defect
from app.models.requests.request import Request
from app.models.work_plans.work_order_blank import WorkOrderBlank
from app.models.work_plans.work_plan import WorkPlan
from app.models.work_plans.work_plan_item import WorkPlanItem
from app.modules.work_orders.order_service import build_order_workbook
from app.modules.work_orders.plan_service import ITEM_COMPLETED

ORDER_FIELDS = (
    "order_number",
    "producer",
    "crew_count",
    "crew_lead",
    "crew_members",
    "lift_responsible",
    "issuer",
    "briefing_conductor",
)


def _clean(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]


class OrderBlankService:
    @staticmethod
    def today() -> date:
        return datetime.now(ZoneInfo("Europe/Moscow")).date()

    @classmethod
    def parse_issued_on(cls, value: str | None) -> date:
        text = (value or "").strip()
        if not text:
            return cls.today()
        try:
            return date.fromisoformat(text)
        except ValueError:
            return cls.today()

    @classmethod
    def for_plan(cls, plan_id: uuid.UUID) -> WorkOrderBlank | None:
        return db.session.scalar(
            select(WorkOrderBlank)
            .options(joinedload(WorkOrderBlank.closed_by))
            .where(WorkOrderBlank.plan_id == plan_id, WorkOrderBlank.active_filter())
        )

    @classmethod
    def for_request_direct(cls, request_id: uuid.UUID) -> WorkOrderBlank | None:
        return db.session.scalar(
            select(WorkOrderBlank)
            .options(joinedload(WorkOrderBlank.closed_by))
            .where(
                WorkOrderBlank.request_id == request_id,
                WorkOrderBlank.plan_id.is_(None),
                WorkOrderBlank.active_filter(),
            )
        )

    @classmethod
    def mark_plan_stale(cls, plan_id: uuid.UUID) -> None:
        blank = cls.for_plan(plan_id)
        if blank is not None:
            blank.needs_update = True

    @classmethod
    def save_plan(
        cls,
        plan: WorkPlan,
        user: User,
        fields: dict[str, str],
        *,
        issued_on: date | None = None,
    ) -> WorkOrderBlank:
        blank = cls.for_plan(plan.id) or WorkOrderBlank(
            plan_id=plan.id,
            created_by=user.id,
        )
        cls._apply_fields(blank, fields, issued_on=issued_on or cls.today())
        blank.closed_by_id = plan.master_id
        blank.needs_update = False
        blank.updated_by = user.id
        db.session.add(blank)
        db.session.commit()
        return cls.for_plan(plan.id) or blank

    @classmethod
    def save_request(
        cls,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        fields: dict[str, str],
        *,
        issued_on: date,
        closed_by_id: uuid.UUID | None,
    ) -> WorkOrderBlank:
        blank = cls.for_request_direct(request_id) or WorkOrderBlank(
            request_id=request_id,
            created_by=user_id,
        )
        cls._apply_fields(blank, fields, issued_on=issued_on)
        blank.closed_by_id = closed_by_id
        blank.needs_update = False
        blank.updated_by = user_id
        db.session.add(blank)
        db.session.commit()
        return cls.for_request_direct(request_id) or blank

    @classmethod
    def _apply_fields(cls, blank: WorkOrderBlank, fields: dict[str, str], *, issued_on: date) -> None:
        number = _clean(fields.get("order_number"), 100)
        blank.order_number = number or None
        blank.issued_on = issued_on
        blank.producer = _clean(fields.get("producer"), 255)
        blank.crew_count = _clean(fields.get("crew_count"), 20) or None
        blank.crew_lead = _clean(fields.get("crew_lead"), 255) or None
        blank.crew_members = _clean(fields.get("crew_members"), 500) or None
        blank.lift_responsible = _clean(fields.get("lift_responsible"), 255) or None
        blank.issuer = _clean(fields.get("issuer"), 255) or None
        blank.briefing_conductor = _clean(fields.get("briefing_conductor"), 255) or None

    @classmethod
    def fields_of(cls, blank: WorkOrderBlank | None) -> dict[str, str]:
        if blank is None:
            return {key: "" for key in ORDER_FIELDS}
        return {
            "order_number": blank.order_number or "",
            "producer": blank.producer or "",
            "crew_count": blank.crew_count or "",
            "crew_lead": blank.crew_lead or "",
            "crew_members": blank.crew_members or "",
            "lift_responsible": blank.lift_responsible or "",
            "issuer": blank.issuer or "",
            "briefing_conductor": blank.briefing_conductor or "",
        }

    @classmethod
    def summary(cls, blank: WorkOrderBlank | None) -> dict:
        if blank is None:
            return {"saved": False, "needs_update": False, "number": "", "issued_on": ""}
        return {
            "saved": True,
            "needs_update": bool(blank.needs_update),
            "number": blank.order_number or "",
            "issued_on": blank.issued_on.isoformat() if blank.issued_on else "",
        }

    @classmethod
    def workbook_for_plan(cls, plan: WorkPlan, blank: WorkOrderBlank, items: list[dict]) -> bytes:
        return build_order_workbook({"items": items}, cls.fields_of(blank))

    @classmethod
    def workbook_for_request(cls, blank: WorkOrderBlank, req: Request) -> bytes:
        item = {
            "number": req.number,
            "pp": req.pp or "",
            "address": req.address or "",
            "description": req.completion_description or req.description or "",
        }
        return build_order_workbook({"items": [item]}, cls.fields_of(blank))

    @classmethod
    def citation_for_request(cls, request_id: uuid.UUID) -> dict | None:
        blank = cls._latest_for_request(request_id)
        return cls._citation(blank, "заявка", "закрыта") if blank else None

    @classmethod
    def citation_for_defect(cls, defect_id: uuid.UUID) -> dict | None:
        blank = cls._latest_plan_blank(defect_id=defect_id)
        return cls._citation(blank, "дефект", "закрыт") if blank else None

    @classmethod
    def _latest_for_request(cls, request_id: uuid.UUID) -> WorkOrderBlank | None:
        found = [row for row in (cls.for_request_direct(request_id), cls._latest_plan_blank(request_id=request_id)) if row]
        if not found:
            return None
        return max(found, key=lambda row: row.updated_at or row.created_at)

    @classmethod
    def _latest_plan_blank(cls, *, request_id: uuid.UUID | None = None, defect_id: uuid.UUID | None = None) -> WorkOrderBlank | None:
        stmt = (
            select(WorkOrderBlank)
            .join(WorkPlan, WorkPlan.id == WorkOrderBlank.plan_id)
            .join(WorkPlanItem, WorkPlanItem.plan_id == WorkPlan.id)
            .options(joinedload(WorkOrderBlank.closed_by))
            .where(
                WorkOrderBlank.active_filter(),
                WorkPlan.active_filter(),
                WorkPlanItem.active_filter(),
                WorkPlanItem.result == ITEM_COMPLETED,
            )
            .order_by(WorkPlanItem.completed_at.desc())
        )
        if request_id is not None:
            stmt = stmt.where(WorkPlanItem.request_id == request_id)
        else:
            stmt = stmt.where(WorkPlanItem.defect_id == defect_id)
        return db.session.scalars(stmt).first()

    @classmethod
    def _citation(cls, blank: WorkOrderBlank, noun: str, verb: str) -> dict:
        master = ""
        if blank.closed_by is not None:
            master = blank.closed_by.full_name
        elif blank.producer:
            master = blank.producer
        issued = blank.issued_on.strftime("%d.%m.%Y") if blank.issued_on else ""
        if blank.order_number:
            title = f"бланку-распоряжению №{blank.order_number}"
        else:
            title = "бланку-распоряжению"
        text = f"Согласно {title} от {issued} {noun} {verb} мастером {master or '—'}."
        return {
            "text": text,
            "download_url": url_for("work_orders.download_saved_order", blank_id=blank.id),
            "number": blank.order_number or "",
            "issued_on": issued,
            "master": master,
        }

    @staticmethod
    def request_item(req: Request) -> dict:
        return {
            "number": req.number,
            "pp": req.pp or "",
            "address": req.address or "",
            "description": req.description or "",
        }

    @staticmethod
    def defect_item(defect: Defect) -> dict:
        return {
            "number": defect.number,
            "pp": defect.pp or "",
            "address": defect.address or "",
            "description": defect.description or "",
        }
