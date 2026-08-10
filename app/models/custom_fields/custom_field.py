"""Определение пользовательского (динамического) поля."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.system_module import SystemModule
    from app.models.custom_fields.custom_field_value import CustomFieldValue
    from app.models.custom_fields.field_option import FieldOption


class CustomField(ActiveRecordMixin, BaseModel):
    """Метаданные динамического поля, создаваемого администратором."""

    __tablename__ = "custom_fields"
    __table_args__ = (
        Index("ix_custom_fields_module_id", "module_id"),
        Index(
            "ix_custom_fields_module_code_unique_active",
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
    field_type: Mapped[str] = mapped_column(String(30), nullable=False, default="text")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    system_module: Mapped[SystemModule] = relationship("SystemModule")
    options: Mapped[list[FieldOption]] = relationship(
        "FieldOption",
        back_populates="custom_field",
        lazy="selectin",
        order_by="FieldOption.sort_order",
    )
    values: Mapped[list[CustomFieldValue]] = relationship(
        "CustomFieldValue",
        back_populates="custom_field",
        lazy="selectin",
    )

    @property
    def module_code(self) -> str | None:
        return self.system_module.code if self.system_module else None

    @property
    def form_name(self) -> str:
        return f"cf_{self.code}"

    def __repr__(self) -> str:
        return f"<CustomField {self.code}>"
