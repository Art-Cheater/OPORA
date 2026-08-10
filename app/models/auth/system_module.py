"""Модуль системы (раздел приложения) для RBAC."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel

if TYPE_CHECKING:
    from app.models.auth.field_definition import FieldDefinition
    from app.models.auth.permission import Permission


class SystemModule(ActiveRecordMixin, BaseModel):
    """Раздел системы — заявки, проекты, договоры и т.д."""

    __tablename__ = "modules"
    __table_args__ = (
        Index(
            "ix_modules_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_modules_sort_order", "sort_order"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    permissions: Mapped[list[Permission]] = relationship(
        "Permission",
        back_populates="system_module",
        lazy="selectin",
    )
    fields: Mapped[list[FieldDefinition]] = relationship(
        "FieldDefinition",
        back_populates="system_module",
        lazy="selectin",
        order_by="FieldDefinition.sort_order",
    )

    def __repr__(self) -> str:
        return f"<SystemModule {self.code}>"
