"""Событие в рамках прогона импорта ЕИС."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID, JSONType

if TYPE_CHECKING:
    from app.models.eis.eis_import_run import EisImportRun


class EisImportEvent(BaseModel):
    """Строка журнала: создано / обновлено / нет объекта / ошибка."""

    __tablename__ = "eis_import_events"
    __table_args__ = (
        Index("ix_eis_import_events_run_id", "run_id"),
        Index("ix_eis_import_events_kind", "kind"),
        Index("ix_eis_import_events_eis_number", "eis_number"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("eis_import_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    eis_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    run: Mapped[EisImportRun] = relationship(
        "EisImportRun",
        back_populates="events",
        foreign_keys=[run_id],
    )

    def __repr__(self) -> str:
        return f"<EisImportEvent {self.kind} {self.eis_number}>"
