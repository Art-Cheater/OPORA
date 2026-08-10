"""Журнал входов пользователей."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User


class LoginLog(BaseModel):
    """Запись журнала входа в систему."""

    __tablename__ = "login_logs"
    __table_args__ = (
        Index("ix_login_logs_user_id", "user_id"),
        Index("ix_login_logs_email", "email"),
        Index("ix_login_logs_success", "success"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped[User | None] = relationship(
        "User",
        back_populates="login_logs",
        foreign_keys=[user_id],
    )

    def __repr__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return f"<LoginLog {self.email} {status}>"
