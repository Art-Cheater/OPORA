"""Справочник журналов нумерации заявок."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel

if TYPE_CHECKING:
    from app.models.requests.request import Request
    from app.models.requests.request_journal_counter import RequestJournalCounter


class RequestJournal(ActiveRecordMixin, BaseModel):
    """Журнал, внутри которого уникален номер заявки."""

    __tablename__ = "request_journals"
    __table_args__ = (
        Index(
            "ix_request_journals_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_request_journals_sort_order", "sort_order"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    requests: Mapped[list[Request]] = relationship(
        "Request",
        back_populates="journal",
        foreign_keys="Request.journal_id",
        lazy="select",
    )
    counters: Mapped[list[RequestJournalCounter]] = relationship(
        "RequestJournalCounter",
        back_populates="journal",
        foreign_keys="RequestJournalCounter.journal_id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<RequestJournal {self.code}>"
