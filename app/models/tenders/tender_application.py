"""Заявка на торги."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, text
from app.models.types import GUID, SearchVectorType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.enums import TenderApplicationStatus

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.contracts.contract import Contract
    from app.models.projects.project import Project
    from app.models.tenders.tender_document import TenderDocument
    from app.models.tenders.tender_project import TenderProject


class TenderApplication(ActiveRecordMixin, BaseModel):
    """Заявка на торги (пакет из нескольких проектов)."""

    __tablename__ = "tender_applications"
    __table_args__ = (
        Index(
            "ix_tender_applications_number_unique_active",
            "number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_tender_applications_status", "status"),
        Index("ix_tender_applications_responsible_id", "responsible_id"),
    )

    number: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default=TenderApplicationStatus.DRAFT.value,
        nullable=False,
    )
    search_vector: Mapped[str | None] = mapped_column(SearchVectorType, nullable=True)

    responsible_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    responsible: Mapped[User | None] = relationship("User", foreign_keys=[responsible_id])
    project_links: Mapped[list[TenderProject]] = relationship(
        "TenderProject",
        back_populates="tender",
        foreign_keys="TenderProject.tender_id",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[TenderDocument]] = relationship(
        "TenderDocument",
        back_populates="tender",
        foreign_keys="TenderDocument.tender_id",
        lazy="selectin",
        order_by="TenderDocument.created_at.desc()",
    )
    contracts: Mapped[list[Contract]] = relationship(
        "Contract",
        back_populates="tender_application",
        foreign_keys="Contract.tender_application_id",
        lazy="select",
    )

    @property
    def projects(self) -> list[Project]:
        return [link.project for link in self.project_links if link.project is not None]

    def __repr__(self) -> str:
        return f"<TenderApplication {self.number}>"
