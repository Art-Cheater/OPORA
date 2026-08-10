"""Связующие таблицы RBAC: user_roles и role_permissions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, utcnow

if TYPE_CHECKING:
    from app.models.auth.permission import Permission
    from app.models.auth.role import Role
    from app.models.auth.user import User


class UserRole(BaseModel):
    """Связь пользователя и роли (Many-to-Many)."""

    __tablename__ = "user_roles"
    __table_args__ = (
        Index("ix_user_roles_user_id", "user_id"),
        Index("ix_user_roles_role_id", "role_id"),
        Index(
            "ix_user_roles_unique_active",
            "user_id",
            "role_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship(
        "User",
        back_populates="user_roles",
        foreign_keys=[user_id],
    )
    role: Mapped[Role] = relationship(
        "Role",
        back_populates="user_roles",
        foreign_keys=[role_id],
    )


class RolePermission(BaseModel):
    """Связь роли и разрешения (Many-to-Many)."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        Index("ix_role_permissions_role_id", "role_id"),
        Index("ix_role_permissions_permission_id", "permission_id"),
        Index(
            "ix_role_permissions_unique_active",
            "role_id",
            "permission_id",
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
    permission_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[Role] = relationship(
        "Role",
        back_populates="role_permissions",
        foreign_keys=[role_id],
    )
    permission: Mapped[Permission] = relationship(
        "Permission",
        back_populates="role_permissions",
        foreign_keys=[permission_id],
    )
