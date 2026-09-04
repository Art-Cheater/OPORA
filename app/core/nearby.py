"""Nearby-поиск открытых заявок и дефектов без полного перебора."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from flask import current_app
from sqlalchemy import and_, func, literal, select, union_all

from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_status import DefectStatus
from app.models.requests.request import Request
from app.models.requests.request_journal import RequestJournal
from app.models.requests.request_status import RequestStatus
from app.modules.requests.address_format import normalize_address
from app.core.routing import RoutingService

PRIORITY_ADDRESS = 1
PRIORITY_STREET = 2
PRIORITY_DISTRICT = 3
PRIORITY_GEO = 4
PRIORITY_PP = 0
GEO_DELTA = Decimal("0.025")
NEARBY_LIMIT = 20


def normalize_pp(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    raw = " ".join(raw.casefold().split())
    return re.sub(r"^пп[\s.:\-]*", "", raw).strip()


def haversine_m(lat1, lon1, lat2, lon2) -> int | None:
    try:
        p1 = math.radians(float(lat1))
        p2 = math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlmb = math.radians(float(lon2) - float(lon1))
    except (TypeError, ValueError):
        return None
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return int(2 * 6371000 * math.asin(min(1.0, math.sqrt(a))))


@dataclass
class NearbyHit:
    entity_type: str
    entity_id: uuid.UUID
    number: str
    address: str
    district: str | None
    street: str | None
    priority: int
    url: str
    description: str = ""
    status: str = ""
    journal: str = ""
    distance_m: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    nearby_reason: str = ""
    pp: str = ""


class NearbySearchService:
    """Предложения ближайших открытых заявок и дефектов. Не создаёт связей и не меняет статусы."""

    @classmethod
    def suggest(
        cls,
        *,
        address: str | None = None,
        street: str | None = None,
        district: str | None = None,
        pp: str | None = None,
        latitude: Decimal | None = None,
        longitude: Decimal | None = None,
        exclude_request_ids: list[uuid.UUID] | None = None,
        exclude_defect_ids: list[uuid.UUID] | None = None,
        limit: int = NEARBY_LIMIT,
    ) -> list[NearbyHit]:
        exclude_request_ids = exclude_request_ids or []
        exclude_defect_ids = exclude_defect_ids or []
        target_address = normalize_address(address) if address else ""
        street_key = (street or "").strip()
        district_key = (district or "").strip()

        parts = []
        pp_key = normalize_pp(pp)
        if pp_key:
            variants = {pp_key, f"пп {pp_key}", f"пп-{pp_key}"}
            req_pp = func.lower(func.trim(Request.pp)).in_(variants)
            def_pp = func.lower(func.trim(Defect.pp)).in_(variants)
            parts.append(cls._request_query(PRIORITY_PP, req_pp, exclude_request_ids))
            parts.append(cls._defect_query(PRIORITY_PP, def_pp, exclude_defect_ids))
        if target_address:
            parts.append(cls._request_query(PRIORITY_ADDRESS, Request.normalized_address == target_address, exclude_request_ids))
            parts.append(cls._defect_query(PRIORITY_ADDRESS, Defect.normalized_address == target_address, exclude_defect_ids))
        if street_key:
            street_filter_req = func.lower(Request.street) == func.lower(literal(street_key))
            street_filter_def = func.lower(Defect.street) == func.lower(literal(street_key))
            if district_key:
                street_filter_req = and_(street_filter_req, Request.district == district_key)
                street_filter_def = and_(street_filter_def, Defect.district == district_key)
            parts.append(cls._request_query(PRIORITY_STREET, street_filter_req, exclude_request_ids))
            parts.append(cls._defect_query(PRIORITY_STREET, street_filter_def, exclude_defect_ids))
        if district_key:
            parts.append(cls._request_query(PRIORITY_DISTRICT, Request.district == district_key, exclude_request_ids))
            parts.append(cls._defect_query(PRIORITY_DISTRICT, Defect.district == district_key, exclude_defect_ids))
        if latitude is not None and longitude is not None:
            lat = Decimal(str(latitude))
            lng = Decimal(str(longitude))
            geo_req = and_(
                Request.latitude.isnot(None),
                Request.longitude.isnot(None),
                Request.latitude.between(lat - GEO_DELTA, lat + GEO_DELTA),
                Request.longitude.between(lng - GEO_DELTA, lng + GEO_DELTA),
            )
            geo_def = and_(
                Defect.latitude.isnot(None),
                Defect.longitude.isnot(None),
                Defect.latitude.between(lat - GEO_DELTA, lat + GEO_DELTA),
                Defect.longitude.between(lng - GEO_DELTA, lng + GEO_DELTA),
            )
            parts.append(cls._request_query(PRIORITY_GEO, geo_req, exclude_request_ids))
            parts.append(cls._defect_query(PRIORITY_GEO, geo_def, exclude_defect_ids))

        if not parts:
            return []

        stmt = union_all(*parts).subquery()
        rows = db.session.execute(
            select(stmt).order_by(stmt.c.priority.asc(), stmt.c.number.asc()).limit(max(limit * 4, 32))
        ).all()

        origin_lat = float(latitude) if latitude is not None else None
        origin_lng = float(longitude) if longitude is not None else None
        seen: set[tuple[str, uuid.UUID]] = set()
        hits: list[NearbyHit] = []
        candidate_limit = current_app.config["NEARBY_ROUTING_CANDIDATE_LIMIT"]
        routed = 0
        max_distance = current_app.config["NEARBY_ROUTE_DISTANCE_METERS"] + current_app.config["NEARBY_ROUTE_TOLERANCE_METERS"]
        # Дорожная длина почти всегда больше прямой; фильтр оставляет запас.
        preliminary_limit = int(max_distance / 0.55)
        for row in rows:
            key = (row.entity_type, row.entity_id)
            if key in seen:
                continue
            seen.add(key)
            lat = float(row.latitude) if row.latitude is not None else None
            lng = float(row.longitude) if row.longitude is not None else None
            same_pp = bool(pp_key) and normalize_pp(row.pp) == pp_key
            distance = None
            reason = "Тот же ПП" if same_pp else ""
            if not same_pp:
                direct = haversine_m(origin_lat, origin_lng, lat, lng) if origin_lat is not None and origin_lng is not None and lat is not None and lng is not None else None
                if direct is None or direct > preliminary_limit or routed >= candidate_limit:
                    continue
                routed += 1
                distance = RoutingService.route_distance((origin_lat, origin_lng), (lat, lng))
                if distance is None or distance > max_distance:
                    continue
            hits.append(
                NearbyHit(
                    entity_type=row.entity_type,
                    entity_id=row.entity_id,
                    number=row.number,
                    address=row.address,
                    district=row.district,
                    street=row.street,
                    priority=int(row.priority),
                    url=(
                        f"/requests/{row.entity_id}"
                        if row.entity_type == "request"
                        else f"/defects/{row.entity_id}"
                    ),
                    description=(row.description or "")[:160],
                    status=row.status_name or "",
                    journal=row.journal_name or "",
                    distance_m=distance,
                    latitude=lat,
                    longitude=lng,
                    nearby_reason=reason,
                    pp=row.pp or "",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    @staticmethod
    def _request_query(priority: int, extra, exclude_ids: list[uuid.UUID]):
        stmt = (
            select(
                literal("request").label("entity_type"),
                Request.id.label("entity_id"),
                Request.number.label("number"),
                Request.address.label("address"),
                Request.district.label("district"),
                Request.street.label("street"),
                literal(priority).label("priority"),
                func.coalesce(Request.description, Request.title).label("description"),
                RequestStatus.name.label("status_name"),
                RequestJournal.name.label("journal_name"),
                Request.latitude.label("latitude"),
                Request.longitude.label("longitude"),
                Request.pp.label("pp"),
            )
            .join(RequestStatus, Request.status_id == RequestStatus.id)
            .join(RequestJournal, Request.journal_id == RequestJournal.id)
            .where(
                Request.active_filter(),
                RequestStatus.active_filter(),
                RequestStatus.is_final.is_(False),
                extra,
            )
        )
        if exclude_ids:
            stmt = stmt.where(Request.id.notin_(exclude_ids))
        return stmt

    @staticmethod
    def _defect_query(priority: int, extra, exclude_ids: list[uuid.UUID]):
        stmt = (
            select(
                literal("defect").label("entity_type"),
                Defect.id.label("entity_id"),
                Defect.number.label("number"),
                Defect.address.label("address"),
                Defect.district.label("district"),
                Defect.street.label("street"),
                literal(priority).label("priority"),
                Defect.description.label("description"),
                DefectStatus.name.label("status_name"),
                literal("Дефекты").label("journal_name"),
                Defect.latitude.label("latitude"),
                Defect.longitude.label("longitude"),
                Defect.pp.label("pp"),
            )
            .join(DefectStatus, Defect.status_id == DefectStatus.id)
            .where(
                Defect.active_filter(),
                DefectStatus.active_filter(),
                DefectStatus.is_final.is_(False),
                extra,
            )
        )
        if exclude_ids:
            stmt = stmt.where(Defect.id.notin_(exclude_ids))
        return stmt

    @classmethod
    def summarize(cls, hits: list[NearbyHit]) -> str:
        requests_n = sum(1 for hit in hits if hit.entity_type == "request")
        defects_n = sum(1 for hit in hits if hit.entity_type == "defect")
        parts = []
        if requests_n:
            parts.append(f"{requests_n} открытых заявок")
        if defects_n:
            parts.append(f"{defects_n} дефектов")
        if not parts:
            return ""
        return "Рядом есть ещё " + " и ".join(parts) + "."
