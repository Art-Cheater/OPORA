"""Права роли на уровне отдельных полей модулей."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.field_definition import FieldDefinition
    from app.models.auth.role import Role

# Уровни доступа к полю
FIELD_ACCESS_NONE = 0
FIELD_ACCESS_VIEW = 1
FIELD_ACCESS_EDIT = 2


class RoleFieldPermission(BaseModel):
    """Какие поля модуля роль может просматривать и редактировать."""

    __tablename__ = "role_field_permissions"
    __table_args__ = (
        Index("ix_role_field_permissions_role_id", "role_id"),
        Index("ix_role_field_permissions_module", "module"),
        Index("ix_role_field_permissions_field_id", "field_id"),
        Index(
            "ix_role_field_permissions_unique_active",
            "role_id",
            "module",
            "field_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("fields.id", ondelete="SET NULL"),
        nullable=True,
    )
    access_level: Mapped[int] = mapped_column(Integer, default=FIELD_ACCESS_VIEW, nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    role: Mapped[Role] = relationship("Role", back_populates="field_permissions")
    field: Mapped[FieldDefinition | None] = relationship("FieldDefinition")

    @staticmethod
    def level_to_flags(level: int) -> tuple[bool, bool]:
        if level >= FIELD_ACCESS_EDIT:
            return True, True
        if level >= FIELD_ACCESS_VIEW:
            return True, False
        return False, False

    @staticmethod
    def flags_to_level(can_view: bool, can_edit: bool) -> int:
        if can_edit:
            return FIELD_ACCESS_EDIT
        if can_view:
            return FIELD_ACCESS_VIEW
        return FIELD_ACCESS_NONE

    def apply_level(self, level: int) -> None:
        self.access_level = level
        self.can_view, self.can_edit = self.level_to_flags(level)
