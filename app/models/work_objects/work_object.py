"""Адресный объект работ (лот), не единица оборудования."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String, Text, text
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
        Index(
            "ix_work_objects_name",
            "name",
        ),
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    plan_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    def __repr__(self) -> str:
        return f"<WorkObject {self.name[:40]}>"
