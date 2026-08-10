"""Вариант выпадающего списка для пользовательского поля."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.custom_fields.custom_field import CustomField


class FieldOption(ActiveRecordMixin, BaseModel):
    """Элемент справочника для поля типа select."""

    __tablename__ = "field_options"
    __table_args__ = (
        Index("ix_field_options_custom_field_id", "custom_field_id"),
        Index(
            "ix_field_options_unique_active",
            "custom_field_id",
            "value",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    custom_field_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("custom_fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    custom_field: Mapped[CustomField] = relationship("CustomField", back_populates="options")

    def __repr__(self) -> str:
        return f"<FieldOption {self.value}>"
