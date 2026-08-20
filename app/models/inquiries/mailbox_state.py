"""Курсор IMAP: какие письма уже забрали с ящика."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, utcnow


class InquiryMailboxState(BaseModel):
    __tablename__ = "inquiry_mailbox_state"
    __table_args__ = (
        UniqueConstraint("mailbox", "folder", name="uq_inquiry_mailbox_folder"),
    )

    mailbox: Mapped[str] = mapped_column(String(255), nullable=False)
    folder: Mapped[str] = mapped_column(String(100), nullable=False, default="INBOX")
    uidvalidity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_uid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    def touch_ok(self) -> None:
        self.last_sync_at = utcnow()
        self.last_error = None

    def __repr__(self) -> str:
        return f"<InquiryMailboxState {self.mailbox} uid={self.last_uid}>"
