"""Выборки обращений."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import joinedload, load_only, noload, undefer

from app.extensions import db
from app.models.auth.user import User
from app.models.inquiries.inquiry import Inquiry


@dataclass
class InquiryFilter:
    q: str = ""
    status: str = ""


def _user_name_options():
    return (
        load_only(User.id, User.full_name),
        noload(User.user_roles),
        noload(User.login_logs),
    )


class InquiryRepository:
    @staticmethod
    def get_by_id(item_id: uuid.UUID) -> Inquiry | None:
        return db.session.scalar(
            db.select(Inquiry)
            .options(
                undefer(Inquiry.body_text),
                undefer(Inquiry.body_html),
                joinedload(Inquiry.assignee).options(*_user_name_options()),
                joinedload(Inquiry.forwarder).options(*_user_name_options()),
                noload(Inquiry.processor),
            )
            .where(Inquiry.id == item_id, Inquiry.deleted_at.is_(None))
        )

    @classmethod
    def paginated_list(
        cls,
        filters: InquiryFilter,
        page: int = 1,
        per_page: int = 30,
        *,
        assigned_to: uuid.UUID | None = None,
    ):
        stmt = (
            db.select(Inquiry)
            .options(
                noload(Inquiry.processor),
                noload(Inquiry.forwarder),
                load_only(
                    Inquiry.id,
                    Inquiry.mailbox,
                    Inquiry.from_name,
                    Inquiry.from_email,
                    Inquiry.subject,
                    Inquiry.received_at,
                    Inquiry.status,
                    Inquiry.attachment_count,
                    Inquiry.created_at,
                    Inquiry.assigned_to,
                ),
                joinedload(Inquiry.assignee).options(*_user_name_options()),
            )
            .where(Inquiry.deleted_at.is_(None))
        )
        if assigned_to is not None:
            stmt = stmt.where(Inquiry.assigned_to == assigned_to)
        q = (filters.q or "").strip()
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                db.or_(
                    Inquiry.subject.ilike(like),
                    Inquiry.from_email.ilike(like),
                    Inquiry.from_name.ilike(like),
                )
            )
        if filters.status:
            stmt = stmt.where(Inquiry.status == filters.status)
        stmt = stmt.order_by(Inquiry.received_at.desc(), Inquiry.created_at.desc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @staticmethod
    def unread_count(*, assigned_to: uuid.UUID | None = None) -> int:
        stmt = (
            db.select(db.func.count())
            .select_from(Inquiry)
            .where(Inquiry.deleted_at.is_(None), Inquiry.status == "new")
        )
        if assigned_to is not None:
            stmt = stmt.where(Inquiry.assigned_to == assigned_to)
        return int(db.session.scalar(stmt) or 0)
