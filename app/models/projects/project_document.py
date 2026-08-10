"""Документы проекта."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import ProjectDocumentType

if TYPE_CHECKING:
    from app.models.projects.project import Project


class ProjectDocument(BaseModel):
    """Формальный документ проекта."""

    __tablename__ = "project_documents"
    __table_args__ = (
        Index("ix_project_documents_project_id", "project_id"),
        Index("ix_project_documents_document_type", "document_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(30),
        default=ProjectDocumentType.OTHER.value,
        nullable=False,
    )
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="documents",
        foreign_keys=[project_id],
    )

    def __repr__(self) -> str:
        return f"<ProjectDocument {self.title}>"
