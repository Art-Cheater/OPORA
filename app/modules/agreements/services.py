"""Сервис договоров на опорах: загрузка Word и поиск по адресу."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_

from sqlalchemy.orm import joinedload

from app.core.exceptions import ValidationError
from app.core.upload_utils import SavedUpload, save_upload
from app.extensions import db
from app.models.agreements.pole_agreement import PoleAgreement
from app.models.agreements.pole_agreement_site import PoleAgreementSite
from app.modules.agreements.parse_docx import parse_agreement_docx
from app.modules.requests.address_format import normalize_address, split_address_query


@dataclass
class AddressHit:
    site: PoleAgreementSite
    agreement: PoleAgreement


class AgreementService:
    @classmethod
    def import_docx(cls, file_storage, user_id: uuid.UUID) -> PoleAgreement:
        saved: SavedUpload = save_upload(file_storage, relative_dir="agreements")
        from flask import current_app

        path = current_app.config["UPLOAD_FOLDER"] / saved.storage_key
        parsed = parse_agreement_docx(path)
        if not parsed.title.strip():
            raise ValidationError("Не удалось прочитать наименование договора.")
        agreement = PoleAgreement(
            title=parsed.title[:500],
            number=(parsed.number or "")[:100] or None,
            subject=(parsed.subject or "")[:1000] or None,
            customer_name=(parsed.customer_name or "")[:500] or None,
            customer_inn=(parsed.customer_inn or "")[:12] or None,
            period_from=parsed.period_from,
            period_to=parsed.period_to,
            source_filename=saved.file_name[:500],
            storage_key=saved.storage_key,
            mime_type=saved.mime_type,
            file_size=saved.file_size,
            parse_warning="; ".join(parsed.warnings) or None,
            uploaded_by=user_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(agreement)
        db.session.flush()
        for index, site in enumerate(parsed.sites):
            db.session.add(
                PoleAgreementSite(
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
            )
        db.session.commit()
        return agreement

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
