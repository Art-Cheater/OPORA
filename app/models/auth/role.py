"""Модель роли."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel

if TYPE_CHECKING:
    from app.models.auth.associations import RolePermission, UserRole
    from app.models.auth.role_field_permission import RoleFieldPermission


class Role(ActiveRecordMixin, BaseModel):
    """Роль пользователя в системе RBAC."""

    __tablename__ = "roles"
    __table_args__ = (
        Index(
            "ix_roles_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_roles_name", "name"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(default=False, nullable=False)

    user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole",
        back_populates="role",
        lazy="select",
    )
    role_permissions: Mapped[list[RolePermission]] = relationship(
        "RolePermission",
        back_populates="role",
        lazy="selectin",
    )
    field_permissions: Mapped[list[RoleFieldPermission]] = relationship(
        "RoleFieldPermission",
        back_populates="role",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Role {self.code}>"
