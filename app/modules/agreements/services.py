"""Сервис договоров на опорах: загрузка Word и поиск по адресу."""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app.core.exceptions import ValidationError
from app.core.upload_utils import SavedUpload, save_upload
from app.extensions import db
from app.models.agreements.pole_agreement import PoleAgreement
from app.models.agreements.pole_agreement_site import PoleAgreementSite
from app.models.base import utcnow
from app.modules.agreements.geocode import geocode_address, geocode_query
from app.modules.agreements.parse_docx import (
    WRONG_AGREEMENT_MESSAGE,
    ParsedAgreement,
    parse_agreement_file,
    normalize_agreement_number,
)
from app.modules.requests.address_format import normalize_address, split_address_query

_geo_lock = threading.Lock()
_geo_started = False


@dataclass
class AddressHit:
    site: PoleAgreementSite
    agreement: PoleAgreement


@dataclass
class MapPoint:
    site_id: uuid.UUID
    agreement_id: uuid.UUID
    lat: float
    lng: float
    address: str
    customer_name: str | None
    title: str
    number: str | None
    subject: str | None
    period: str
    mounts_count: int | None
    poles_count: int | None
    note: str | None
    has_file: bool


@dataclass
class ImportOutcome:
    agreement: PoleAgreement
    created: bool
    duplicates_hidden: int = 0


def _period_label(agreement: PoleAgreement) -> str:
    start = agreement.period_from.strftime("%d.%m.%Y") if agreement.period_from else "—"
    end = agreement.period_to.strftime("%d.%m.%Y") if agreement.period_to else "—"
    if start == "—" and end == "—":
        return "—"
    return f"{start} — {end}"


def _apply_coords(site: PoleAgreementSite, coords: tuple[float, float] | None) -> None:
    if coords is None:
        return
    site.latitude = Decimal(str(coords[0]))
    site.longitude = Decimal(str(coords[1]))


def _coord_index() -> dict[str, tuple[float, float]]:
    stmt = (
        db.select(PoleAgreementSite)
        .join(PoleAgreement, PoleAgreementSite.agreement_id == PoleAgreement.id)
        .where(
            PoleAgreement.active_filter(),
            PoleAgreementSite.deleted_at.is_(None),
            PoleAgreementSite.latitude.isnot(None),
            PoleAgreementSite.longitude.isnot(None),
        )
    )
    index: dict[str, tuple[float, float]] = {}
    for site in db.session.scalars(stmt):
        index.setdefault(geocode_query(site.address), (float(site.latitude), float(site.longitude)))
    return index


def _apply_known_coords(sites: list[PoleAgreementSite], index: dict[str, tuple[float, float]] | None = None) -> int:
    known = index if index is not None else _coord_index()
    placed = 0
    for site in sites:
        if site.latitude is not None and site.longitude is not None:
            continue
        coords = known.get(geocode_query(site.address))
        if coords is None:
            continue
        _apply_coords(site, coords)
        placed += 1
    return placed


class AgreementService:
    @classmethod
    def collapse_duplicates(cls, user_id: uuid.UUID | None = None) -> int:
        rows = list(
            db.session.scalars(
                db.select(PoleAgreement)
                .options(selectinload(PoleAgreement.sites))
                .where(PoleAgreement.active_filter())
            )
        )
        groups: dict[str, list[PoleAgreement]] = defaultdict(list)
        for item in rows:
            key = normalize_agreement_number(item.number)
            if key:
                groups[key].append(item)
        hidden = 0
        for items in groups.values():
            if len(items) < 2:
                continue
            winner = max(
                items,
                key=lambda item: (
                    len(item.sites),
                    item.updated_at or item.created_at,
                    item.created_at,
                ),
            )
            for item in items:
                if item.id == winner.id:
                    continue
                item.deleted_at = utcnow()
                if user_id is not None:
                    item.updated_by = user_id
                hidden += 1
        if hidden:
            db.session.commit()
        return hidden

    @classmethod
    def find_by_number(cls, number: str | None) -> PoleAgreement | None:
        key = normalize_agreement_number(number)
        if not key:
            return None
        rows = list(
            db.session.scalars(
                db.select(PoleAgreement)
                .options(selectinload(PoleAgreement.sites))
                .where(PoleAgreement.active_filter())
            )
        )
        matches = [item for item in rows if normalize_agreement_number(item.number) == key]
        if not matches:
            return None
        return max(
            matches,
            key=lambda item: (len(item.sites), item.updated_at or item.created_at, item.created_at),
        )

    @classmethod
    def import_docx(cls, file_storage, user_id: uuid.UUID) -> ImportOutcome:
        from flask import current_app

        hidden = cls.collapse_duplicates(user_id)
        saved: SavedUpload = save_upload(file_storage, relative_dir="agreements")
        path = Path(current_app.config["UPLOAD_FOLDER"]) / saved.storage_key
        parsed = parse_agreement_file(path)
        if not parsed.sites or WRONG_AGREEMENT_MESSAGE in parsed.warnings:
            path.unlink(missing_ok=True)
            raise ValidationError(WRONG_AGREEMENT_MESSAGE)

        existing = cls.find_by_number(parsed.number)
        created = existing is None
        known = _coord_index()
        if existing is not None:
            for site in existing.sites:
                if site.latitude is not None and site.longitude is not None:
                    known.setdefault(
                        geocode_query(site.address),
                        (float(site.latitude), float(site.longitude)),
                    )
            old_key = existing.storage_key
            cls._apply_parsed_fields(existing, parsed, saved, user_id)
            existing.sites.clear()
            db.session.flush()
            cls._add_sites(existing, parsed, user_id, known)
            if old_key and old_key != saved.storage_key:
                (Path(current_app.config["UPLOAD_FOLDER"]) / old_key).unlink(missing_ok=True)
            agreement = existing
        else:
            agreement = PoleAgreement(
                uploaded_by=user_id,
                created_by=user_id,
            )
            cls._apply_parsed_fields(agreement, parsed, saved, user_id)
            db.session.add(agreement)
            db.session.flush()
            cls._add_sites(agreement, parsed, user_id, known)

        db.session.commit()
        cls.ensure_background_geocode()
        return ImportOutcome(agreement=agreement, created=created, duplicates_hidden=hidden)

    @staticmethod
    def _apply_parsed_fields(
        agreement: PoleAgreement,
        parsed: ParsedAgreement,
        saved: SavedUpload,
        user_id: uuid.UUID,
    ) -> None:
        agreement.title = parsed.title[:500]
        agreement.number = (parsed.number or "")[:100] or None
        if parsed.subject:
            agreement.subject = parsed.subject[:1000]
        if parsed.customer_name:
            agreement.customer_name = parsed.customer_name[:500]
        if parsed.customer_inn:
            agreement.customer_inn = parsed.customer_inn[:12]
        if parsed.period_from:
            agreement.period_from = parsed.period_from
        if parsed.period_to:
            agreement.period_to = parsed.period_to
        agreement.source_filename = saved.file_name[:500]
        agreement.storage_key = saved.storage_key
        agreement.mime_type = saved.mime_type
        agreement.file_size = saved.file_size
        agreement.parse_warning = "; ".join(parsed.warnings) or None
        agreement.updated_by = user_id

    @staticmethod
    def _add_sites(
        agreement: PoleAgreement,
        parsed: ParsedAgreement,
        user_id: uuid.UUID,
        known: dict[str, tuple[float, float]],
    ) -> None:
        for index, site in enumerate(parsed.sites):
            row = PoleAgreementSite(
                agreement_id=agreement.id,
                sort_order=index,
                row_no=(site.row_no or "")[:30] or None,
                address=site.address[:2000],
                address_norm=normalize_address(site.address)[:2000] or None,
                mounts_count=site.mounts_count,
                poles_count=site.poles_count,
                note=site.note,
                extra=site.extra or None,
                created_by=user_id,
                updated_by=user_id,
            )
            _apply_known_coords([row], known)
            agreement.sites.append(row)

    @classmethod
    def hydrate_missing_coords(cls, *, agreement_id: uuid.UUID | None = None) -> int:
        stmt = (
            db.select(PoleAgreementSite)
            .join(PoleAgreement, PoleAgreementSite.agreement_id == PoleAgreement.id)
            .where(
                PoleAgreement.active_filter(),
                PoleAgreementSite.deleted_at.is_(None),
                PoleAgreementSite.latitude.is_(None),
            )
        )
        if agreement_id is not None:
            stmt = stmt.where(PoleAgreementSite.agreement_id == agreement_id)
        rows = list(db.session.scalars(stmt))
        placed = _apply_known_coords(rows)
        if placed:
            db.session.commit()
        return placed

    @classmethod
    def geocode_missing(cls, *, agreement_id: uuid.UUID | None = None, limit: int = 8) -> int:
        placed = cls.hydrate_missing_coords(agreement_id=agreement_id)
        stmt = (
            db.select(PoleAgreementSite)
            .join(PoleAgreement, PoleAgreementSite.agreement_id == PoleAgreement.id)
            .where(
                PoleAgreement.active_filter(),
                PoleAgreementSite.deleted_at.is_(None),
                PoleAgreementSite.latitude.is_(None),
            )
            .order_by(PoleAgreementSite.sort_order)
        )
        if agreement_id is not None:
            stmt = stmt.where(PoleAgreementSite.agreement_id == agreement_id)
        rows = list(db.session.scalars(stmt))
        groups: dict[str, list[PoleAgreementSite]] = defaultdict(list)
        for site in rows:
            groups[geocode_query(site.address)].append(site)
        done = 0
        for _query, group in groups.items():
            if done >= max(1, min(int(limit), 15)):
                break
            coords = geocode_address(group[0].address)
            done += 1
            if coords is None:
                continue
            for site in group:
                if site.latitude is None:
                    _apply_coords(site, coords)
                    placed += 1
        if placed:
            db.session.commit()
        return placed

    @classmethod
    def ensure_background_geocode(cls) -> None:
        from flask import current_app

        if current_app.config.get("TESTING"):
            return
        global _geo_started
        app = current_app._get_current_object()
        with _geo_lock:
            if _geo_started:
                return
            _geo_started = True

        def run() -> None:
            global _geo_started
            try:
                with app.app_context():
                    idle = 0
                    while idle < 3:
                        if cls.geocode_missing(limit=8):
                            idle = 0
                        else:
                            idle += 1
            finally:
                with _geo_lock:
                    _geo_started = False

        threading.Thread(target=run, daemon=True, name="agreement-geocode").start()

    @classmethod
    def map_points(cls, *, agreement_id: uuid.UUID | None = None) -> tuple[list[MapPoint], int]:
        stmt = (
            db.select(PoleAgreementSite)
            .options(joinedload(PoleAgreementSite.agreement))
            .join(PoleAgreement, PoleAgreementSite.agreement_id == PoleAgreement.id)
            .where(
                PoleAgreement.active_filter(),
                PoleAgreementSite.deleted_at.is_(None),
            )
            .order_by(PoleAgreement.customer_name, PoleAgreementSite.sort_order)
        )
        if agreement_id is not None:
            stmt = stmt.where(PoleAgreementSite.agreement_id == agreement_id)
        rows = list(db.session.scalars(stmt).unique())
        points: list[MapPoint] = []
        remaining = 0
        for site in rows:
            if site.latitude is None or site.longitude is None:
                remaining += 1
                continue
            agreement = site.agreement
            points.append(
                MapPoint(
                    site_id=site.id,
                    agreement_id=agreement.id,
                    lat=float(site.latitude),
                    lng=float(site.longitude),
                    address=site.address,
                    customer_name=agreement.customer_name,
                    title=agreement.title,
                    number=agreement.number,
                    subject=agreement.subject,
                    period=_period_label(agreement),
                    mounts_count=site.mounts_count,
                    poles_count=site.poles_count,
                    note=site.note,
                    has_file=bool(agreement.storage_key),
                )
            )
        return points, remaining

    @classmethod
    def search_address(cls, query: str) -> list[AddressHit]:
        text = (query or "").strip()
        if not text:
            return []
        like = f"%{text}%"
        stmt = (
            db.select(PoleAgreementSite)
            .options(joinedload(PoleAgreementSite.agreement))
            .join(PoleAgreement, PoleAgreementSite.agreement_id == PoleAgreement.id)
            .where(
                PoleAgreement.active_filter(),
                PoleAgreementSite.deleted_at.is_(None),
                or_(
                    PoleAgreementSite.address.ilike(like),
                    PoleAgreementSite.address_norm.ilike(like),
                ),
            )
            .order_by(PoleAgreement.customer_name, PoleAgreementSite.sort_order)
        )
        rows = list(db.session.scalars(stmt))
        if rows:
            return [AddressHit(site=item, agreement=item.agreement) for item in rows]

        _, street_name, house = split_address_query(text)
        tokens = [part for part in (street_name, house) if part]
        if not tokens:
            return []
        extra = list(
            db.session.scalars(
                db.select(PoleAgreementSite)
                .join(PoleAgreement, PoleAgreementSite.agreement_id == PoleAgreement.id)
                .where(PoleAgreement.active_filter(), PoleAgreementSite.deleted_at.is_(None))
            )
        )
        hits: list[AddressHit] = []
        needles = [item.casefold() for item in tokens]
        for site in extra:
            hay = f"{site.address or ''} {site.address_norm or ''}".casefold()
            if all(needle in hay for needle in needles):
                hits.append(AddressHit(site=site, agreement=site.agreement))
        return hits
