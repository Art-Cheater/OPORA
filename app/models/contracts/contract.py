"""Модель контракта."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text, text
from app.models.types import GUID, SearchVectorType
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import ContractStatus, ContractType

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.contractors.contractor import Contractor
    from app.models.contracts.contract_contractor import ContractContractor
    from app.models.contracts.contract_document import ContractDocument
    from app.models.contracts.contract_history import ContractHistory
    from app.models.contracts.contract_object import ContractObject
    from app.models.projects.project import Project
    from app.models.tenders.tender_application import TenderApplication
    from app.models.work_objects.work_object import WorkObject


class Contract(BaseModel):
    """Контракт / договор (может включать несколько объектов)."""

    __tablename__ = "contracts"
    __table_args__ = (
        Index(
            "ix_contracts_number_unique_active",
            "number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_contracts_project_id", "project_id"),
        Index("ix_contracts_tender_application_id", "tender_application_id"),
        Index("ix_contracts_status", "status"),
        Index("ix_contracts_contract_type", "contract_type"),
        Index("ix_contracts_responsible_id", "responsible_id"),
        Index("ix_contracts_contract_date", "contract_date"),
        Index("ix_contracts_start_date", "start_date"),
        Index("ix_contracts_deleted_created", "deleted_at", "created_at"),
        Index(
            "ix_contracts_eis_reestr_unique_active",
            "eis_reestr_number",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND eis_reestr_number IS NOT NULL AND eis_reestr_number != ''"
            ),
            sqlite_where=text(
                "deleted_at IS NULL AND eis_reestr_number IS NOT NULL AND eis_reestr_number != ''"
            ),
        ),
    )

    contract_type: Mapped[str] = mapped_column(
        String(30),
        default=ContractType.OTHER.value,
        nullable=False,
    )
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contractor_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default=ContractStatus.DRAFT.value,
        nullable=False,
    )
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    eis_reestr_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    eis_stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    eis_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    delivery_place: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[str | None] = deferred(
        mapped_column(SearchVectorType, nullable=True)
    )

    responsible_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    tender_application_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("tender_applications.id", ondelete="SET NULL"),
        nullable=True,
    )

    responsible: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[responsible_id],
    )
    project: Mapped[Project | None] = relationship(
        "Project",
        back_populates="contracts",
        foreign_keys=[project_id],
    )
    tender_application: Mapped[TenderApplication | None] = relationship(
        "TenderApplication",
        back_populates="contracts",
        foreign_keys=[tender_application_id],
    )
    contractor_links: Mapped[list[ContractContractor]] = relationship(
        "ContractContractor",
        back_populates="contract",
        foreign_keys="ContractContractor.contract_id",
        lazy="select",
        cascade="all, delete-orphan",
    )
    object_links: Mapped[list[ContractObject]] = relationship(
        "ContractObject",
        back_populates="contract",
        foreign_keys="ContractObject.contract_id",
        # select: список договоров не должен тянуть объекты, историю и файлы
        lazy="select",
        cascade="all, delete-orphan",
    )
    history: Mapped[list[ContractHistory]] = relationship(
        "ContractHistory",
        back_populates="contract",
        foreign_keys="ContractHistory.contract_id",
        lazy="select",
        order_by="ContractHistory.created_at.desc()",
    )
    documents: Mapped[list[ContractDocument]] = relationship(
        "ContractDocument",
        back_populates="contract",
        foreign_keys="ContractDocument.contract_id",
        lazy="select",
        order_by="ContractDocument.created_at.desc()",
    )

    @property
    def work_objects(self) -> list[WorkObject]:
        return [
            link.work_object
            for link in self.object_links
            if link.deleted_at is None
            and link.work_object is not None
            and link.work_object.deleted_at is None
        ]

    @property
    def contractors(self) -> list[Contractor]:
        return [
            link.contractor
            for link in self.contractor_links
            if link.contractor is not None and link.deleted_at is None
        ]

    def __repr__(self) -> str:
        return f"<Contract {self.number}>"
