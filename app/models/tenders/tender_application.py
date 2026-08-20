"""Заявка на торги."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.enums import TenderApplicationStatus
from app.models.types import GUID, SearchVectorType

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.contracts.contract import Contract
    from app.models.projects.project import Project
    from app.models.tenders.tender_document import TenderDocument
    from app.models.tenders.tender_project import TenderProject
    from app.models.work_objects.work_object import WorkObject


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
        Index("ix_tender_applications_object_id", "object_id"),
        Index("ix_tender_applications_deleted_created", "deleted_at", "created_at"),
        Index("ix_tender_applications_work_deadline_date", "work_deadline_date"),
        Index(
            "ix_tender_applications_eis_reg_unique_active",
            "eis_reg_number",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND eis_reg_number IS NOT NULL AND eis_reg_number != ''"
            ),
            sqlite_where=text(
                "deleted_at IS NULL AND eis_reg_number IS NOT NULL AND eis_reg_number != ''"
            ),
        ),
    )

    number: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default=TenderApplicationStatus.DRAFT.value,
        nullable=False,
    )
    search_vector: Mapped[str | None] = deferred(
        mapped_column(SearchVectorType, nullable=True)
    )

    object_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("work_objects.id", ondelete="SET NULL"),
        nullable=True,
    )
    work_deadline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    work_deadline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    nmck: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    eis_reg_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    eis_status: Mapped[str | None] = mapped_column(String(200), nullable=True)
    eis_url: Mapped[str | None] = mapped_column(String(700), nullable=True)

    responsible_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    responsible: Mapped[User | None] = relationship("User", foreign_keys=[responsible_id])
    work_object: Mapped[WorkObject | None] = relationship(
        "WorkObject",
        foreign_keys=[object_id],
    )
    project_links: Mapped[list[TenderProject]] = relationship(
        "TenderProject",
        back_populates="tender",
        foreign_keys="TenderProject.tender_id",
        # select, не selectin: список торгов не должен тянуть состав и документы
        lazy="select",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[TenderDocument]] = relationship(
        "TenderDocument",
        back_populates="tender",
        foreign_keys="TenderDocument.tender_id",
        lazy="select",
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
