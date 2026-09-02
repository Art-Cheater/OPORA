"""Nearby-поиск открытых заявок и дефектов без полного перебора."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, literal, or_, select, union_all

from app.extensions import db
from app.models.defects.defect import Defect
from app.models.defects.defect_status import DefectStatus
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.address_format import normalize_address

PRIORITY_ADDRESS = 1
PRIORITY_STREET = 2
PRIORITY_DISTRICT = 3
PRIORITY_GEO = 4
GEO_DELTA = Decimal("0.007")
NEARBY_LIMIT = 20


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


class NearbySearchService:
    """Предложения ближайших открытых заявок и дефектов."""

    @classmethod
    def suggest(
        cls,
        *,
        address: str | None = None,
        street: str | None = None,
        district: str | None = None,
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
            select(stmt).order_by(stmt.c.priority.asc(), stmt.c.number.asc()).limit(limit * 3)
        ).all()

        seen: set[tuple[str, uuid.UUID]] = set()
        hits: list[NearbyHit] = []
        for row in rows:
            key = (row.entity_type, row.entity_id)
            if key in seen:
                continue
            seen.add(key)
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
            )
            .join(RequestStatus, Request.status_id == RequestStatus.id)
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
