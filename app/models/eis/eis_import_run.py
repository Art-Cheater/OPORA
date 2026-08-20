"""Журнал прогонов импорта ЕИС."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, utcnow
from app.models.types import GUID, JSONType

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.eis.eis_import_event import EisImportEvent


class EisImportRun(BaseModel):
    """Один запуск парсера ЕИС (по расписанию или вручную)."""

    __tablename__ = "eis_import_runs"
    __table_args__ = (
        Index("ix_eis_import_runs_started_at", "started_at"),
        Index("ix_eis_import_runs_status", "status"),
        Index("ix_eis_import_runs_user_id", "user_id"),
    )

    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])
    events: Mapped[list[EisImportEvent]] = relationship(
        "EisImportEvent",
        back_populates="run",
        foreign_keys="EisImportEvent.run_id",
        lazy="select",
        order_by="EisImportEvent.created_at.asc()",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<EisImportRun {self.status} {self.started_at}>"
