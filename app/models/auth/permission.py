"""Модель разрешения."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.associations import RolePermission
    from app.models.auth.system_module import SystemModule


class Permission(ActiveRecordMixin, BaseModel):
    """Разрешение (permission) в системе RBAC."""

    __tablename__ = "permissions"
    __table_args__ = (
        Index(
            "ix_permissions_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_permissions_module", "module"),
        Index("ix_permissions_module_id", "module_id"),
        Index("ix_permissions_action", "action"),
    )

    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="view")
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("modules.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    system_module: Mapped[SystemModule | None] = relationship(
        "SystemModule",
        back_populates="permissions",
    )
    role_permissions: Mapped[list[RolePermission]] = relationship(
        "RolePermission",
        back_populates="permission",
        # select: иначе каждый запрос с permissions тянет все привязки ролей
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"
