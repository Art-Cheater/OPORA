"""Карточки сущностей Опоры в сообщениях мессенджера."""

from __future__ import annotations

import uuid

from flask import url_for
from sqlalchemy.orm import load_only, noload

from app.extensions import db
from app.models.agreements.pole_agreement import PoleAgreement
from app.models.auth.constants import (
    PERM_AGREEMENTS_VIEW,
    PERM_CONTRACTS_VIEW,
    PERM_INQUIRIES_VIEW,
    PERM_PROJECTS_VIEW,
)
from app.models.contracts.contract import Contract
from app.models.inquiries.inquiry import Inquiry
from app.models.projects.project import Project
from app.modules.inquiries.access import can_access_inquiry, manages_mailbox

CARD_TYPES = {
    "inquiry": {
        "label": "Письмо",
        "icon": "envelope",
        "permission": PERM_INQUIRIES_VIEW,
    },
    "contract": {
        "label": "Контракт",
        "icon": "file-earmark-text",
        "permission": PERM_CONTRACTS_VIEW,
    },
    "project": {
        "label": "Проект",
        "icon": "folder2-open",
        "permission": PERM_PROJECTS_VIEW,
    },
    "agreement": {
        "label": "Договор",
        "icon": "broadcast",
        "permission": PERM_AGREEMENTS_VIEW,
    },
}


def card_meta(card_type: str) -> dict:
    return CARD_TYPES.get(card_type) or {"label": "Карточка", "icon": "link-45deg"}


def available_types(user) -> list[dict]:
    return [
        {"type": key, "label": meta["label"], "icon": meta["icon"]}
        for key, meta in CARD_TYPES.items()
        if user.has_permission(meta["permission"])
    ]


def snapshot_inquiry(inquiry: Inquiry) -> dict:
    sender = inquiry.from_name or inquiry.from_email or "Отправитель неизвестен"
    return {
        "type": "inquiry",
        "id": str(inquiry.id),
        "title": inquiry.subject or "(без темы)",
        "subtitle": sender,
        "url": url_for("inquiries.detail", inquiry_id=inquiry.id),
        "label": CARD_TYPES["inquiry"]["label"],
        "icon": CARD_TYPES["inquiry"]["icon"],
    }


def resolve_card(user, entity_type: str, entity_id: uuid.UUID) -> dict | None:
    meta = CARD_TYPES.get(entity_type)
    if meta is None or not user.has_permission(meta["permission"]):
        return None
    if entity_type == "inquiry":
        inquiry = db.session.scalar(
            db.select(Inquiry)
            .options(
                load_only(
                    Inquiry.id,
                    Inquiry.subject,
                    Inquiry.from_name,
                    Inquiry.from_email,
                    Inquiry.assigned_to,
                ),
                noload(Inquiry.processor),
                noload(Inquiry.assignee),
                noload(Inquiry.forwarder),
            )
            .where(Inquiry.id == entity_id, Inquiry.deleted_at.is_(None))
        )
        if inquiry is None or not can_access_inquiry(user, inquiry):
            return None
        return snapshot_inquiry(inquiry)
    if entity_type == "contract":
        item = db.session.scalar(
            db.select(Contract)
            .options(load_only(Contract.id, Contract.number, Contract.title, Contract.contractor_name))
            .where(Contract.id == entity_id, Contract.active_filter())
        )
        if item is None:
            return None
        return {
            "type": "contract",
            "id": str(item.id),
            "title": f"{item.number} · {item.title}",
            "subtitle": item.contractor_name or "",
            "url": url_for("contracts.detail", contract_id=item.id),
            "label": meta["label"],
            "icon": meta["icon"],
        }
    if entity_type == "project":
        item = db.session.scalar(
            db.select(Project)
            .options(load_only(Project.id, Project.code, Project.name))
            .where(Project.id == entity_id, Project.active_filter())
        )
        if item is None:
            return None
        return {
            "type": "project",
            "id": str(item.id),
            "title": f"{item.code} · {item.name}",
            "subtitle": "",
            "url": url_for("projects.detail", project_id=item.id),
            "label": meta["label"],
            "icon": meta["icon"],
        }
    item = db.session.scalar(
        db.select(PoleAgreement)
        .options(
            load_only(
                PoleAgreement.id,
                PoleAgreement.title,
                PoleAgreement.number,
                PoleAgreement.customer_name,
            )
        )
        .where(PoleAgreement.id == entity_id, PoleAgreement.active_filter())
    )
    if item is None:
        return None
    subtitle = " · ".join(part for part in (item.number, item.customer_name) if part)
    return {
        "type": "agreement",
        "id": str(item.id),
        "title": item.title,
        "subtitle": subtitle,
        "url": url_for("agreements.detail", agreement_id=item.id),
        "label": meta["label"],
        "icon": meta["icon"],
    }


def search_cards(user, entity_type: str, query: str, *, limit: int = 8) -> list[dict]:
    meta = CARD_TYPES.get(entity_type)
    if meta is None or not user.has_permission(meta["permission"]):
        return []
    limit = max(1, min(int(limit), 20))
    q = (query or "").strip()
    like = f"%{q}%" if q else None

    if entity_type == "inquiry":
        from app.modules.inquiries.repositories import InquiryFilter, InquiryRepository

        assigned_to = None if manages_mailbox(user) else user.id
        pagination = InquiryRepository.paginated_list(
            InquiryFilter(q=q),
            page=1,
            per_page=limit,
            assigned_to=assigned_to,
        )
        return [snapshot_inquiry(item) for item in pagination.items]

    if entity_type == "contract":
        stmt = db.select(Contract).options(
            load_only(Contract.id, Contract.number, Contract.title, Contract.contractor_name)
        ).where(Contract.active_filter())
        if like:
            stmt = stmt.where(
                db.or_(
                    Contract.number.ilike(like),
                    Contract.title.ilike(like),
                    Contract.contractor_name.ilike(like),
                )
            )
        stmt = stmt.order_by(Contract.updated_at.desc()).limit(limit)
        return [resolve_card(user, "contract", item.id) for item in db.session.scalars(stmt) if item]

    if entity_type == "project":
        stmt = db.select(Project).options(
            load_only(Project.id, Project.code, Project.name)
        ).where(Project.active_filter())
        if like:
            stmt = stmt.where(
                db.or_(Project.code.ilike(like), Project.name.ilike(like))
            )
        stmt = stmt.order_by(Project.updated_at.desc()).limit(limit)
        return [resolve_card(user, "project", item.id) for item in db.session.scalars(stmt) if item]

    stmt = db.select(PoleAgreement).options(
        load_only(
            PoleAgreement.id,
            PoleAgreement.title,
            PoleAgreement.number,
            PoleAgreement.customer_name,
        )
    ).where(PoleAgreement.active_filter())
    if like:
        stmt = stmt.where(
            db.or_(
                PoleAgreement.title.ilike(like),
                PoleAgreement.number.ilike(like),
                PoleAgreement.customer_name.ilike(like),
            )
        )
    stmt = stmt.order_by(PoleAgreement.created_at.desc()).limit(limit)
    return [resolve_card(user, "agreement", item.id) for item in db.session.scalars(stmt) if item]
