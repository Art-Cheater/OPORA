"""Уведомления пользователей."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import NotificationType


class Notification(BaseModel):
    """Уведомление пользователя."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id", "user_id"),
        Index("ix_notifications_is_read", "is_read"),
        Index("ix_notifications_entity", "entity_type", "entity_id"),
        Index("ix_notifications_type", "type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(
        String(20),
        default=NotificationType.INFO.value,
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<Notification {self.id} user={self.user_id}>"
