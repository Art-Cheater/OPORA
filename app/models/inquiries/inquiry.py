"""Входящее письмо-обращение с корпоративного ящика."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.user import User

STATUS_NEW = "new"
STATUS_SEEN = "seen"
STATUS_DONE = "done"

STATUS_LABELS = {
    STATUS_NEW: "Новое",
    STATUS_SEEN: "Просмотрено",
    STATUS_DONE: "Обработано",
}


class Inquiry(BaseModel):
    __tablename__ = "inquiries"
    __table_args__ = (
        UniqueConstraint("mailbox", "imap_uidvalidity", "imap_uid", name="uq_inquiries_imap_uid"),
        Index("ix_inquiries_received_at", "received_at"),
        Index("ix_inquiries_status", "status"),
        Index("ix_inquiries_from_email", "from_email"),
        Index("ix_inquiries_message_id", "message_id"),
        Index("ix_inquiries_deleted_received", "deleted_at", "received_at"),
    )

    mailbox: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_uid: Mapped[int] = mapped_column(Integer, nullable=False)
    imap_uidvalidity: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    from_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_email: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subject: Mapped[str] = mapped_column(String(1000), nullable=False, default="(без темы)")
    body_text: Mapped[str | None] = deferred(mapped_column(Text, nullable=True))
    body_html: Mapped[str | None] = deferred(mapped_column(Text, nullable=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_NEW)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    processed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    processor: Mapped[User | None] = relationship("User", foreign_keys=[processed_by])

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def __repr__(self) -> str:
        return f"<Inquiry {self.subject[:40]}>"
