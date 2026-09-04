"""Сбор точек, nearby и сериализация плана работ мастера."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from flask import url_for
from sqlalchemy import case, false as sa_false, func, literal, or_, select, union_all
from sqlalchemy.orm import joinedload, load_only, selectinload

from app.core.nearby import NearbyHit, NearbySearchService
from app.extensions import db
from app.models.auth.constants import (
    PERM_DEFECTS_EDIT,
    PERM_DEFECTS_STATUS_CHANGE,
)
from app.models.auth.user import User
from app.models.defects.defect import Defect
from app.models.defects.defect_history import DefectHistory
from app.models.defects.defect_status import DefectStatus
from app.models.enums import EntityType, Priority
from app.models.files.attachment import Attachment
from app.models.requests.request import Request
from app.models.requests.request_history import RequestHistory
from app.models.requests.request_journal import RequestJournal
from app.models.requests.request_status import RequestStatus
from app.models.waybills.waybill import Waybill
from app.models.waybills.waybill_stop import WaybillStop
from app.modules.defects.workflow import STATUS_FIXED as DEFECT_FIXED
from app.modules.defects.workflow import STATUS_IN_PROGRESS as DEFECT_IN_PROGRESS
from app.modules.defects.workflow import STATUS_OPEN as DEFECT_OPEN
from app.modules.requests.repositories import RequestRepository
from app.modules.requests.workflow import (
    OPEN_STATUS_CODES,
    STATUS_COMPLETED,
    STATUS_NEW,
    available_actions,
)
from app.modules.waybills.repositories import WaybillRepository
from app.modules.waybills.services import WaybillPayload, WaybillService
from app.modules.waybills.workflow import STATUS_DRAFT, STATUS_IN_PROGRESS, status_label


@dataclass
class WorkOrderFilter:
    kind: str = "all"  # all | request | defect | villages
    q: str = ""
    pp: str = ""
    district: str = ""
    journal_id: str = ""
    status_id: str = ""
    responsible_id: str = ""
    work_date: str = ""
    active_only: bool = True


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _short(text: str | None, limit: int = 120) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _day_bounds(value: str) -> tuple[datetime, datetime] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)
    return start, end


class WorkOrderService:
    """План дня мастера на базе Waybill / WaybillStop."""

    @staticmethod
    def today_plan(user_id: uuid.UUID) -> Waybill | None:
        return db.session.scalar(
            db.select(Waybill)
            .options(
                joinedload(Waybill.master),
                selectinload(Waybill.stops).joinedload(WaybillStop.request).joinedload(Request.status),
                selectinload(Waybill.stops).joinedload(WaybillStop.request).joinedload(Request.journal),
                selectinload(Waybill.stops).joinedload(WaybillStop.defect).joinedload(Defect.status),
            )
            .where(
                Waybill.master_id == user_id,
                Waybill.work_date == date.today(),
                Waybill.status.in_([STATUS_DRAFT, STATUS_IN_PROGRESS]),
                Waybill.active_filter(),
            )
            .order_by(
                case((Waybill.status == STATUS_IN_PROGRESS, 0), else_=1),
                Waybill.created_at.desc(),
            )
        )

    @classmethod
    def today_draft(cls, user_id: uuid.UUID) -> Waybill | None:
        return cls.today_plan(user_id)

    @classmethod
    def get_or_create_today_draft(cls, user: User) -> Waybill:
        existing = cls.today_plan(user.id)
        if existing is not None:
            return existing
        return WaybillService.create(
            WaybillPayload(
                number=WaybillRepository.next_number(),
                work_date=date.today(),
                master_id=user.id,
                comment="План работ на сегодня",
                member_ids=[],
            ),
            user.id,
        )

    @classmethod
    def map_points(cls, filters: WorkOrderFilter, plan: Waybill | None) -> list[dict]:
        """Карта рабочего места показывает только уже выбранные работы."""
        if plan is None:
            return []
        points = []
        for order, stop in enumerate(sorted((s for s in plan.stops if s.deleted_at is None), key=lambda s: s.sort_order), start=1):
            row = cls.serialize_stop(stop, order)
            if row["lat"] is not None and row["lng"] is not None:
                row["stop_id"] = row["id"]
                row["id"] = row["entity_id"]
                row["type"] = row["entity_type"]
                row["in_plan"] = True
                points.append(row)
        return points

    @classmethod
    def list_items(cls, filters: WorkOrderFilter, plan: Waybill | None, limit: int = 80) -> list[dict]:
        in_plan = cls._plan_keys(plan)
        items: list[dict] = []
        if filters.kind in {"all", "request", "villages"}:
            items.extend(cls._request_points(filters, in_plan, with_coords=False, limit=limit))
        if filters.kind in {"all", "defect"}:
            items.extend(cls._defect_points(filters, in_plan, with_coords=False, limit=limit))
        items.sort(key=lambda row: (row.get("number") or ""))
        return items[:limit]

    @staticmethod
    def _plan_keys(plan: Waybill | None) -> set[tuple[str, str]]:
        if plan is None:
            return set()
        keys: set[tuple[str, str]] = set()
        for stop in plan.stops:
            if stop.deleted_at is not None:
                continue
            if stop.request_id:
                keys.add(("request", str(stop.request_id)))
            if stop.defect_id:
                keys.add(("defect", str(stop.defect_id)))
        return keys

    @classmethod
    def _request_points(
        cls,
        filters: WorkOrderFilter,
        in_plan: set[tuple[str, str]],
        *,
        with_coords: bool,
        limit: int = 500,
    ) -> list[dict]:
        stmt = (
            db.select(Request)
            .options(
                load_only(
                    Request.id,
                    Request.number,
                    Request.address,
                    Request.description,
                    Request.title,
                    Request.district,
                    Request.latitude,
                    Request.longitude,
                    Request.status_id,
                    Request.journal_id,
                    Request.responsible_id,
                    Request.received_at,
                    Request.pp,
                ),
                joinedload(Request.status),
                joinedload(Request.journal),
            )
            .join(RequestStatus, Request.status_id == RequestStatus.id)
            .where(Request.active_filter())
        )
        if with_coords:
            stmt = stmt.where(Request.latitude.isnot(None), Request.longitude.isnot(None))
        if filters.active_only:
            stmt = stmt.where(RequestStatus.is_final.is_(False), RequestStatus.active_filter())
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(db.or_(Request.number.ilike(q), Request.address.ilike(q), Request.title.ilike(q), Request.pp.ilike(q)))
        if filters.pp:
            stmt = stmt.where(Request.pp.ilike(f"%{filters.pp.strip()}%"))
        if filters.district:
            stmt = stmt.where(Request.district == filters.district)
        if filters.kind == "villages":
            from app.modules.requests.journals import (
                JOURNAL_LENINSKY_VILLAGES,
                JOURNAL_NOVOVYATSKY_VILLAGES,
                JOURNAL_OKTYABRSKY_VILLAGES,
            )

            village_ids = [
                item.id
                for item in cls.journals()
                if item.code in {
                    JOURNAL_OKTYABRSKY_VILLAGES,
                    JOURNAL_NOVOVYATSKY_VILLAGES,
                    JOURNAL_LENINSKY_VILLAGES,
                }
            ]
            stmt = stmt.where(Request.journal_id.in_(village_ids) if village_ids else sa_false())
        elif filters.kind == "request":
            from app.modules.requests.journals import JOURNAL_MAIN

            main = RequestRepository.get_journal_by_code(JOURNAL_MAIN)
            if main is not None:
                stmt = stmt.where(Request.journal_id == main.id)
        journal_id = _uuid_or_none(filters.journal_id)
        if journal_id:
            stmt = stmt.where(Request.journal_id == journal_id)
        status_id = _uuid_or_none(filters.status_id)
        if status_id:
            stmt = stmt.where(Request.status_id == status_id)
        responsible_id = _uuid_or_none(filters.responsible_id)
        if responsible_id:
            stmt = stmt.where(Request.responsible_id == responsible_id)
        bounds = _day_bounds(filters.work_date)
        if bounds:
            stmt = stmt.where(Request.received_at.between(bounds[0], bounds[1]))
        stmt = stmt.order_by(Request.received_at.desc().nullslast(), Request.created_at.desc()).limit(limit)
        rows = []
        for item in db.session.scalars(stmt).unique():
            rows.append(cls._request_dict(item, in_plan))
        return rows

    @classmethod
    def _defect_points(
        cls,
        filters: WorkOrderFilter,
        in_plan: set[tuple[str, str]],
        *,
        with_coords: bool,
        limit: int = 500,
    ) -> list[dict]:
        stmt = (
            db.select(Defect)
            .options(
                load_only(
                    Defect.id,
                    Defect.number,
                    Defect.address,
                    Defect.description,
                    Defect.district,
                    Defect.latitude,
                    Defect.longitude,
                    Defect.status_id,
                    Defect.responsible_id,
                    Defect.created_at,
                    Defect.pp,
                ),
                joinedload(Defect.status),
            )
            .join(DefectStatus, Defect.status_id == DefectStatus.id)
            .where(Defect.active_filter())
        )
        if with_coords:
            stmt = stmt.where(Defect.latitude.isnot(None), Defect.longitude.isnot(None))
        if filters.active_only:
            stmt = stmt.where(DefectStatus.is_final.is_(False), DefectStatus.active_filter())
        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(db.or_(Defect.number.ilike(q), Defect.address.ilike(q), Defect.description.ilike(q), Defect.pp.ilike(q)))
        if filters.pp:
            stmt = stmt.where(Defect.pp.ilike(f"%{filters.pp.strip()}%"))
        if filters.district:
            stmt = stmt.where(Defect.district == filters.district)
        status_id = _uuid_or_none(filters.status_id)
        if status_id:
            stmt = stmt.where(Defect.status_id == status_id)
        responsible_id = _uuid_or_none(filters.responsible_id)
        if responsible_id:
            stmt = stmt.where(Defect.responsible_id == responsible_id)
        bounds = _day_bounds(filters.work_date)
        if bounds:
            stmt = stmt.where(Defect.created_at.between(bounds[0], bounds[1]))
        stmt = stmt.order_by(Defect.created_at.desc()).limit(limit)
        return [cls._defect_dict(item, in_plan) for item in db.session.scalars(stmt).unique()]

    @staticmethod
    def _request_dict(item: Request, in_plan: set[tuple[str, str]]) -> dict:
        lat = float(item.latitude) if item.latitude is not None else None
        lng = float(item.longitude) if item.longitude is not None else None
        return {
            "id": str(item.id),
            "type": "request",
            "number": item.number,
            "address": item.address or "",
            "description": _short(item.description or item.title),
            "status": item.status.name if item.status else "",
            "status_code": item.status.code if item.status else "",
            "journal": item.journal.name if item.journal else "",
            "district": item.district or "",
            "pp": item.pp or "",
            "lat": lat,
            "lng": lng,
            "url": f"/requests/{item.id}?return_url=/work-orders/",
            "in_plan": ("request", str(item.id)) in in_plan,
            "color": "blue",
        }

    @staticmethod
    def _defect_dict(item: Defect, in_plan: set[tuple[str, str]]) -> dict:
        lat = float(item.latitude) if item.latitude is not None else None
        lng = float(item.longitude) if item.longitude is not None else None
        return {
            "id": str(item.id),
            "type": "defect",
            "number": item.number,
            "address": item.address or "",
            "description": _short(item.description),
            "status": item.status.name if item.status else "",
            "status_code": item.status.code if item.status else "",
            "journal": "Дефекты",
            "district": item.district or "",
            "pp": item.pp or "",
            "lat": lat,
            "lng": lng,
            "url": f"/defects/{item.id}?return_url=/work-orders/",
            "in_plan": ("defect", str(item.id)) in in_plan,
            "color": "red",
        }

    @classmethod
    def serialize_plan(cls, plan: Waybill | None) -> dict:
        if plan is None:
            return {
                "id": None,
                "number": None,
                "work_date": None,
                "work_date_label": "",
                "status": None,
                "status_label": "",
                "title": "Мой план работ",
                "editable": True,
                "stops": [],
            }
        stops = [s for s in plan.stops if s.deleted_at is None]
        stops.sort(key=lambda s: s.sort_order)
        work_date_label = plan.work_date.strftime("%d.%m.%Y") if plan.work_date else ""
        return {
            "id": str(plan.id),
            "number": plan.number,
            "work_date": plan.work_date.isoformat() if plan.work_date else None,
            "work_date_label": work_date_label,
            "status": plan.status,
            "status_label": status_label(plan.status),
            "title": f"План работ на {work_date_label}" if work_date_label else "Мой план работ",
            "editable": plan.status in {STATUS_DRAFT, STATUS_IN_PROGRESS},
            "stops": [cls.serialize_stop(stop, index) for index, stop in enumerate(stops, start=1)],
        }

    @staticmethod
    def serialize_stop(stop: WaybillStop, order: int | None = None) -> dict:
        request = stop.request
        defect = stop.defect
        entity_type = "request" if stop.request_id else "defect"
        entity = request if request is not None else defect
        latitude = stop.latitude if stop.latitude is not None else (entity.latitude if entity is not None else None)
        longitude = stop.longitude if stop.longitude is not None else (entity.longitude if entity is not None else None)
        number = entity.number if entity is not None else ""
        description = ""
        status = ""
        journal = ""
        url = ""
        if request is not None:
            description = _short(request.description or request.title)
            status = request.status.name if request.status else ""
            journal = request.journal.name if request.journal else ""
            url = f"/requests/{request.id}?return_url=/work-orders/"
        elif defect is not None:
            description = _short(defect.description)
            status = defect.status.name if defect.status else ""
            journal = "Дефекты"
            url = f"/defects/{defect.id}?return_url=/work-orders/"
        return {
            "id": str(stop.id),
            "order": order if order is not None else stop.sort_order,
            "entity_type": entity_type,
            "entity_id": str(stop.request_id or stop.defect_id),
            "number": number,
            "address": stop.address or "",
            "description": description,
            "status": status,
            "journal": journal,
            "url": url,
            "lat": float(latitude) if latitude is not None else None,
            "lng": float(longitude) if longitude is not None else None,
            "color": "blue" if entity_type == "request" else "red",
        }

    @classmethod
    def nearby_for(cls, entity_type: str, entity_id: uuid.UUID, plan: Waybill | None):
        exclude_req = [s.request_id for s in (plan.stops if plan else []) if s.request_id and s.deleted_at is None]
        exclude_def = [s.defect_id for s in (plan.stops if plan else []) if s.defect_id and s.deleted_at is None]
        if entity_type == "request":
            item = db.session.scalar(
                db.select(Request).options(joinedload(Request.journal)).where(Request.id == entity_id, Request.active_filter())
            )
            if item is None:
                return [], ""
            exclude_req.append(item.id)
            hits = NearbySearchService.suggest(
                address=item.address,
                street=item.street,
                district=item.district,
                pp=item.pp,
                latitude=item.latitude,
                longitude=item.longitude,
                exclude_request_ids=exclude_req,
                exclude_defect_ids=exclude_def,
            )
        elif entity_type == "defect":
            item = db.session.scalar(db.select(Defect).where(Defect.id == entity_id, Defect.active_filter()))
            if item is None:
                return [], ""
            exclude_def.append(item.id)
            hits = NearbySearchService.suggest(
                address=item.address,
                street=item.street,
                district=item.district,
                pp=item.pp,
                latitude=item.latitude,
                longitude=item.longitude,
                exclude_request_ids=exclude_req,
                exclude_defect_ids=exclude_def,
            )
        else:
            return [], ""
        return hits, NearbySearchService.summarize(hits)

    @staticmethod
    def hit_to_dict(hit: NearbyHit) -> dict:
        return {
            "entity_type": hit.entity_type,
            "entity_id": str(hit.entity_id),
            "number": hit.number,
            "address": hit.address,
            "description": hit.description,
            "status": hit.status,
            "journal": hit.journal,
            "priority": hit.priority,
            "distance_m": hit.distance_m,
            "nearby_reason": hit.nearby_reason,
            "pp": hit.pp,
            "lat": hit.latitude,
            "lng": hit.longitude,
            "type_label": "Заявка" if hit.entity_type == "request" else "Дефект",
            "url": (
                f"/requests/{hit.entity_id}?return_url=/work-orders/"
                if hit.entity_type == "request"
                else f"/defects/{hit.entity_id}?return_url=/work-orders/"
            ),
            "color": "blue" if hit.entity_type == "request" else "red",
        }

    @staticmethod
    def journals():
        return list(
            db.session.scalars(
                db.select(RequestJournal).where(RequestJournal.active_filter()).order_by(RequestJournal.sort_order)
            )
        )

    QUEUE_PAGE = 30
    QUEUE_PRESETS = {
        "all": None,
        "new": (STATUS_NEW,),
        "in_progress": tuple(code for code in OPEN_STATUS_CODES if code != STATUS_NEW),
        "completed": (STATUS_COMPLETED,),
    }
    DEFECT_PRESETS = {
        "all": None,
        "new": (DEFECT_OPEN,),
        "in_progress": (DEFECT_IN_PROGRESS,),
        "completed": (DEFECT_FIXED,),
    }
    PRIORITY_LABELS = {
        Priority.LOW.value: "Низкий",
        Priority.MEDIUM.value: "Средний",
        Priority.HIGH.value: "Высокий",
        Priority.CRITICAL.value: "Критичный",
    }

    @staticmethod
    def _fmt_dt(value) -> str:
        if value is None:
            return ""
        try:
            return value.strftime("%d.%m.%Y %H:%M")
        except (AttributeError, TypeError, ValueError):
            return str(value)

    @staticmethod
    def _can_complete_defect(item: Defect, user: User) -> bool:
        code = item.status.code if item.status else ""
        if code not in {DEFECT_OPEN, DEFECT_IN_PROGRESS}:
            return False
        return user.has_permission(PERM_DEFECTS_EDIT) or user.has_permission(PERM_DEFECTS_STATUS_CHANGE)

    @classmethod
    def queue(cls, *, preset: str, q: str, page: int, user: User, journal: str = "all", open_only: bool = False) -> dict:
        journal_key = (journal or "all").strip().lower()
        codes = cls.QUEUE_PRESETS.get((preset or "all").strip().lower(), cls.QUEUE_PRESETS["all"])
        defect_codes = cls.DEFECT_PRESETS.get((preset or "all").strip().lower(), cls.DEFECT_PRESETS["all"])
        if open_only:
            codes = tuple(OPEN_STATUS_CODES) if not codes else tuple(code for code in codes if code in OPEN_STATUS_CODES)
            defect_codes = (DEFECT_OPEN, DEFECT_IN_PROGRESS) if not defect_codes else tuple(
                code for code in defect_codes if code in {DEFECT_OPEN, DEFECT_IN_PROGRESS}
            )
        needle = (q or "").strip()
        like = f"%{needle}%" if needle else None
        include_requests = journal_key != "defects"
        include_defects = journal_key in {"all", "defects"}
        journal_id = None
        if include_requests and journal_key not in {"all", "defects"}:
            found = RequestRepository.get_journal_by_code(journal_key)
            if found is None:
                include_requests = False
            else:
                journal_id = found.id

        parts = []
        if include_requests:
            req_stmt = (
                db.select(
                    Request.id.label("eid"),
                    literal("request").label("kind"),
                    func.coalesce(Request.received_at, Request.created_at).label("sort_at"),
                )
                .join(RequestStatus, Request.status_id == RequestStatus.id)
                .where(Request.active_filter())
            )
            if codes:
                req_stmt = req_stmt.where(RequestStatus.code.in_(codes))
            if journal_id is not None:
                req_stmt = req_stmt.where(Request.journal_id == journal_id)
            if like:
                req_stmt = req_stmt.where(
                    or_(
                        Request.number.ilike(like),
                        Request.address.ilike(like),
                        Request.description.ilike(like),
                        Request.dispatcher_name.ilike(like),
                        Request.applicant_name.ilike(like),
                        Request.pp.ilike(like),
                        Request.street.ilike(like),
                    )
                )
            parts.append(req_stmt)
        if include_defects:
            def_stmt = (
                db.select(
                    Defect.id.label("eid"),
                    literal("defect").label("kind"),
                    Defect.created_at.label("sort_at"),
                )
                .join(DefectStatus, Defect.status_id == DefectStatus.id)
                .where(Defect.active_filter())
            )
            if defect_codes:
                def_stmt = def_stmt.where(DefectStatus.code.in_(defect_codes))
            if like:
                def_stmt = def_stmt.where(
                    or_(
                        Defect.number.ilike(like),
                        Defect.address.ilike(like),
                        Defect.description.ilike(like),
                        Defect.pp.ilike(like),
                        Defect.street.ilike(like),
                    )
                )
            parts.append(def_stmt)

        page_num = max(page, 1)
        if not parts:
            return {"items": [], "page": page_num, "pages": 1, "total": 0}

        unioned = union_all(*parts).subquery()
        total = db.session.scalar(select(func.count()).select_from(unioned)) or 0
        pages = max((total + cls.QUEUE_PAGE - 1) // cls.QUEUE_PAGE, 1)
        rows = db.session.execute(
            select(unioned.c.eid, unioned.c.kind)
            .order_by(unioned.c.sort_at.desc())
            .offset((page_num - 1) * cls.QUEUE_PAGE)
            .limit(cls.QUEUE_PAGE)
        ).all()
        request_ids = [row.eid for row in rows if row.kind == "request"]
        defect_ids = [row.eid for row in rows if row.kind == "defect"]
        requests = {}
        defects = {}
        if request_ids:
            requests = {
                item.id: item
                for item in db.session.scalars(
                    db.select(Request)
                    .options(joinedload(Request.status), joinedload(Request.journal))
                    .where(Request.id.in_(request_ids))
                ).unique()
            }
        if defect_ids:
            defects = {
                item.id: item
                for item in db.session.scalars(
                    db.select(Defect)
                    .options(joinedload(Defect.status))
                    .where(Defect.id.in_(defect_ids))
                ).unique()
            }
        items = []
        for row in rows:
            if row.kind == "request" and row.eid in requests:
                items.append(cls.serialize_queue_item(requests[row.eid], user))
            elif row.kind == "defect" and row.eid in defects:
                items.append(cls.serialize_defect_queue_item(defects[row.eid], user))
        return {"items": items, "page": page_num, "pages": pages, "total": total}

    @classmethod
    def serialize_queue_item(cls, item: Request, user: User) -> dict:
        actions = available_actions(item, user)
        return {
            "id": str(item.id),
            "entity_type": "request",
            "type": "request",
            "type_label": "Заявка",
            "number": item.number,
            "status": item.status.name if item.status else "",
            "status_code": item.status.code if item.status else "",
            "address": item.address or "",
            "district": item.district or "",
            "pp": item.pp or "",
            "journal": item.journal.name if item.journal else "",
            "description": (item.description or item.title or "")[:180],
            "received_at": cls._fmt_dt(item.received_at or item.created_at),
            "dispatcher_name": item.dispatcher_name or "",
            "can_complete": any(action.code == "complete" for action in actions),
        }

    @classmethod
    def serialize_defect_queue_item(cls, item: Defect, user: User) -> dict:
        return {
            "id": str(item.id),
            "entity_type": "defect",
            "type": "defect",
            "type_label": "Дефект",
            "number": item.number,
            "status": item.status.name if item.status else "",
            "status_code": item.status.code if item.status else "",
            "address": item.address or "",
            "district": item.district or "",
            "pp": item.pp or "",
            "journal": "Дефекты",
            "description": (item.description or "")[:180],
            "received_at": cls._fmt_dt(item.created_at),
            "dispatcher_name": "",
            "can_complete": cls._can_complete_defect(item, user),
        }

    @classmethod
    def entity_card(cls, entity_type: str, entity_id: uuid.UUID, user: User) -> dict | None:
        if entity_type == "defect":
            return cls.defect_card(entity_id, user)
        return cls.card(entity_id, user)

    @classmethod
    def card(cls, request_id: uuid.UUID, user: User) -> dict | None:
        item = db.session.scalar(
            db.select(Request)
            .options(
                joinedload(Request.status),
                joinedload(Request.journal),
                selectinload(Request.history).joinedload(RequestHistory.status),
                selectinload(Request.history).joinedload(RequestHistory.changed_by_user),
            )
            .where(Request.id == request_id, Request.active_filter())
        )
        if item is None:
            return None
        attachments = list(
            db.session.scalars(
                db.select(Attachment)
                .where(
                    Attachment.entity_type == EntityType.REQUEST.value,
                    Attachment.entity_id == item.id,
                    Attachment.active_filter(),
                )
                .order_by(Attachment.created_at.desc())
            )
        )
        photos = []
        documents = []
        for file in attachments:
            payload = {
                "id": str(file.id),
                "name": file.file_name,
                "mime": file.mime_type or "",
                "created_at": cls._fmt_dt(file.created_at),
                "preview_url": url_for(
                    "requests.download_attachment",
                    request_id=item.id,
                    attachment_id=file.id,
                    inline=1,
                ),
                "download_url": url_for(
                    "requests.download_attachment",
                    request_id=item.id,
                    attachment_id=file.id,
                ),
            }
            if (file.mime_type or "").startswith("image/"):
                photos.append(payload)
            else:
                documents.append(payload)
        history = []
        for entry in sorted(item.history or [], key=lambda row: row.created_at or row.id, reverse=True):
            history.append(
                {
                    "id": str(entry.id),
                    "action": entry.action or "",
                    "comment": entry.comment or "",
                    "status": entry.status.name if entry.status else "",
                    "user": entry.changed_by_user.full_name if entry.changed_by_user else "",
                    "created_at": cls._fmt_dt(entry.created_at),
                }
            )
        queue = cls.serialize_queue_item(item, user)
        queue.update(
            {
                "title": item.title or "",
                "description": item.description or "",
                "pp": item.pp or "",
                "journal": item.journal.name if item.journal else "",
                "priority": cls.PRIORITY_LABELS.get(item.priority or "", item.priority or ""),
                "applicant_name": item.applicant_name or "",
                "phone": item.phone or "",
                "settlement": item.settlement or "",
                "street": item.street or "",
                "house": item.house or "",
                "has_barrier": bool(item.has_barrier),
                "barrier_phone": item.barrier_phone or "",
                "photos": photos,
                "documents": documents,
                "history": history,
            }
        )
        return queue

    @classmethod
    def defect_card(cls, defect_id: uuid.UUID, user: User) -> dict | None:
        item = db.session.scalar(
            db.select(Defect)
            .options(
                joinedload(Defect.status),
                joinedload(Defect.category),
                selectinload(Defect.history).joinedload(DefectHistory.status),
                selectinload(Defect.history).joinedload(DefectHistory.changed_by_user),
            )
            .where(Defect.id == defect_id, Defect.active_filter())
        )
        if item is None:
            return None
        attachments = list(
            db.session.scalars(
                db.select(Attachment)
                .where(
                    Attachment.entity_type == EntityType.DEFECT.value,
                    Attachment.entity_id == item.id,
                    Attachment.active_filter(),
                )
                .order_by(Attachment.created_at.desc())
            )
        )
        photos = []
        documents = []
        for file in attachments:
            payload = {
                "id": str(file.id),
                "name": file.file_name,
                "mime": file.mime_type or "",
                "created_at": cls._fmt_dt(file.created_at),
                "preview_url": url_for(
                    "defects.download_attachment",
                    defect_id=item.id,
                    attachment_id=file.id,
                    inline=1,
                ),
                "download_url": url_for(
                    "defects.download_attachment",
                    defect_id=item.id,
                    attachment_id=file.id,
                ),
            }
            if (file.mime_type or "").startswith("image/"):
                photos.append(payload)
            else:
                documents.append(payload)
        history = []
        for entry in sorted(item.history or [], key=lambda row: row.created_at or row.id, reverse=True):
            history.append(
                {
                    "id": str(entry.id),
                    "action": entry.action or "",
                    "comment": entry.comment or "",
                    "status": entry.status.name if entry.status else "",
                    "user": entry.changed_by_user.full_name if entry.changed_by_user else "",
                    "created_at": cls._fmt_dt(entry.created_at),
                }
            )
        queue = cls.serialize_defect_queue_item(item, user)
        queue.update(
            {
                "title": "",
                "description": item.description or "",
                "pp": item.pp or "",
                "journal": "Дефекты",
                "priority": "",
                "applicant_name": "",
                "phone": "",
                "settlement": item.settlement or "",
                "street": item.street or "",
                "house": item.house or "",
                "has_barrier": False,
                "barrier_phone": "",
                "category": item.category.name if item.category else "",
                "photos": photos,
                "documents": documents,
                "history": history,
            }
        )
        return queue
