"""Онлайн-статус пользователя."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, utcnow

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.auth.user import User


class UserPresence(BaseModel):
    """Присутствие пользователя в мессенджере."""

    __tablename__ = "user_presence"
    __table_args__ = (
        Index(
            "ix_user_presence_user_id_unique",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<UserPresence user={self.user_id}>"
