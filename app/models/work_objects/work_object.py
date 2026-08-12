"""Адресный объект работ (лот), не единица оборудования."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.enums import WorkObjectStatus
from app.models.types import SearchVectorType

if TYPE_CHECKING:
    from app.models.projects.project import Project


class WorkObject(ActiveRecordMixin, BaseModel):
    """Объект = адресный лот наружного освещения."""

    __tablename__ = "work_objects"
    __table_args__ = (
        Index("ix_work_objects_status", "status"),
        Index("ix_work_objects_plan_year", "plan_year"),
        Index("ix_work_objects_name", "name"),
        Index("ix_work_objects_contract_number", "contract_number"),
    )

    # name — отображаемое (обычно адрес); work_type — «Устройство наружного освещения»
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    work_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    plan_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_deadline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contract_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contractor_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contract_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    result_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_sheet: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default=WorkObjectStatus.FREE.value,
        nullable=False,
    )
    search_vector: Mapped[str | None] = mapped_column(SearchVectorType, nullable=True)

    projects: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="work_object",
        foreign_keys="Project.object_id",
        lazy="select",
    )

    @property
    def display_address(self) -> str:
        return self.address or self.name or "—"

    def __repr__(self) -> str:
        label = self.address or self.name
        return f"<WorkObject {label[:40]}>"
