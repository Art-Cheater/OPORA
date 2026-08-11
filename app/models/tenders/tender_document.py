"""Документы заявки на торги."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import TenderDocumentType

if TYPE_CHECKING:
    from app.models.tenders.tender_application import TenderApplication


class TenderDocument(BaseModel):
    """Документ заявки на торги."""

    __tablename__ = "tender_documents"
    __table_args__ = (
        Index("ix_tender_documents_tender_id", "tender_id"),
        Index("ix_tender_documents_document_type", "document_type"),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("tender_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(30),
        default=TenderDocumentType.OTHER.value,
        nullable=False,
    )
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    tender: Mapped[TenderApplication] = relationship(
        "TenderApplication",
        back_populates="documents",
        foreign_keys=[tender_id],
    )

    def __repr__(self) -> str:
        return f"<TenderDocument {self.title}>"
