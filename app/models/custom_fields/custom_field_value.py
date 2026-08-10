"""Значение пользовательского поля для конкретного объекта."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.custom_fields.custom_field import CustomField


class CustomFieldValue(BaseModel):
    """EAV-значение: объект + поле → данные."""

    __tablename__ = "custom_field_values"
    __table_args__ = (
        Index("ix_custom_field_values_entity", "entity_type", "entity_id"),
        Index("ix_custom_field_values_custom_field_id", "custom_field_id"),
        Index("ix_custom_field_values_value_text", "value_text"),
        Index(
            "ix_custom_field_values_unique_active",
            "custom_field_id",
            "entity_type",
            "entity_id",
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
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    custom_field: Mapped[CustomField] = relationship("CustomField", back_populates="values")

    def __repr__(self) -> str:
        return f"<CustomFieldValue {self.entity_type}:{self.entity_id}>"
