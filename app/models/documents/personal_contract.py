"""Личный договор/контракт сотрудника (раздел «Документы»)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.files.attachment import Attachment


class PersonalContract(BaseModel):
    """Договор в личных документах: файл + извлечённые реквизиты и срок."""

    __tablename__ = "personal_contracts"
    __table_args__ = (
        Index("ix_personal_contracts_user_id", "user_id"),
        Index("ix_personal_contracts_ends_on", "ends_on"),
        Index("ix_personal_contracts_attachment_id", "attachment_id", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reminded_month_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reminded_two_weeks_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    attachment: Mapped[Attachment] = relationship("Attachment", foreign_keys=[attachment_id])

    def __repr__(self) -> str:
        return f"<PersonalContract {self.id} user={self.user_id}>"
