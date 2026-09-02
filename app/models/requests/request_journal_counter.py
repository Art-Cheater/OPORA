"""Счётчик нумерации заявок внутри журнала и года."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.requests.request_journal import RequestJournal


class RequestJournalCounter(BaseModel):
    """Последний выданный порядковый номер YY-N в журнале за календарный год."""

    __tablename__ = "request_journal_counters"
    __table_args__ = (
        UniqueConstraint("journal_id", "year", name="uq_request_journal_counters_journal_year"),
        Index("ix_request_journal_counters_journal_id", "journal_id"),
    )

    journal_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("request_journals.id", ondelete="CASCADE"),
        nullable=False,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    journal: Mapped[RequestJournal] = relationship(
        "RequestJournal",
        back_populates="counters",
        foreign_keys=[journal_id],
    )

    def __repr__(self) -> str:
        return f"<RequestJournalCounter {self.journal_id} {self.year}={self.last_value}>"
