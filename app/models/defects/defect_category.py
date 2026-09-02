"""Категории дефектов."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel

if TYPE_CHECKING:
    from app.models.defects.defect import Defect


class DefectCategory(ActiveRecordMixin, BaseModel):
    """Тип/категория дефекта."""

    __tablename__ = "defect_categories"
    __table_args__ = (
        Index(
            "ix_defect_categories_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_defect_categories_sort_order", "sort_order"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    defects: Mapped[list[Defect]] = relationship(
        "Defect",
        back_populates="category",
        foreign_keys="Defect.category_id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<DefectCategory {self.code}>"
