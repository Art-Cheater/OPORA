"""Определение поля сущности модуля для настройки прав."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Boolean, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.system_module import SystemModule


class FieldDefinition(ActiveRecordMixin, BaseModel):
    """Поле объекта модуля (например, «Адрес» в заявках)."""

    __tablename__ = "fields"
    __table_args__ = (
        Index("ix_fields_module_id", "module_id"),
        Index(
            "ix_fields_module_code_unique_active",
            "module_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    module_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    system_module: Mapped[SystemModule] = relationship(
        "SystemModule",
        back_populates="fields",
    )

    def __repr__(self) -> str:
        return f"<FieldDefinition {self.code}>"
