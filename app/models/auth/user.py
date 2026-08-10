"""Модель пользователя."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from app.models.types import GUID, SearchVectorType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import hash_password, verify_password
from app.models.base import BaseModel, utcnow

if TYPE_CHECKING:
    from app.models.auth.associations import UserRole
    from app.models.auth.login_log import LoginLog
    from app.models.auth.position import Position
    from app.models.auth.role import Role


class User(UserMixin, BaseModel):
    """Пользователь системы «Опора»."""

    __tablename__ = "users"
    __table_args__ = (
        Index(
            "ix_users_email_unique_active",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_full_name", "full_name"),
        Index("ix_users_is_blocked", "is_blocked"),
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
    )
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    search_vector: Mapped[str | None] = mapped_column(SearchVectorType, nullable=True)

    # Явная колонка: перекрывает property is_active из Flask-Login UserMixin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    blocked_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole",
        back_populates="user",
        foreign_keys="UserRole.user_id",
        lazy="selectin",
    )
    login_logs: Mapped[list[LoginLog]] = relationship(
        "LoginLog",
        back_populates="user",
        foreign_keys="LoginLog.user_id",
        # Не selectin: иначе при любом списке пользователей тянется весь журнал входов
        lazy="select",
    )
    blocker: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[blocked_by],
        remote_side="User.id",
    )
    position_ref: Mapped[Position | None] = relationship(
        "Position",
        back_populates="users",
        foreign_keys=[position_id],
    )

    @property
    def position_title(self) -> str | None:
        if self.position_ref is not None:
            return self.position_ref.name
        return self.position

    def set_password(self, password: str) -> None:
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        if self.password_hash.startswith("$2"):
            return verify_password(password, self.password_hash)
        # Поддержка legacy-хешей (werkzeug) при миграции на bcrypt
        from werkzeug.security import check_password_hash

        return check_password_hash(self.password_hash, password)

    def get_id(self) -> str:
        return str(self.id)

    @property
    def can_login(self) -> bool:
        """Пользователь может войти в систему."""
        return self.is_active and not self.is_blocked and self.deleted_at is None

    @property
    def roles(self) -> list[Role]:
        return [
            ur.role
            for ur in self.user_roles
            if ur.deleted_at is None
            and ur.role is not None
            and ur.role.deleted_at is None
            and ur.role.is_active
        ]

    @property
    def role_codes(self) -> list[str]:
        return [role.code for role in self.roles]

    @property
    def role_names(self) -> list[str]:
        return [role.name for role in self.roles]

    def has_role(self, role_code: str) -> bool:
        return role_code in self.role_codes

    def has_any_role(self, *role_codes: str) -> bool:
        return any(self.has_role(code) for code in role_codes)

    def has_permission(self, permission_code: str) -> bool:
        from app.core.permission_service import PermissionService

        return PermissionService.has_permission(self, permission_code)

    def has_any_permission(self, *permission_codes: str) -> bool:
        return any(self.has_permission(code) for code in permission_codes)

    def can_view_field(self, module: str, field_name: str) -> bool:
        from app.core.permission_service import PermissionService

        return PermissionService.can_view_field(self, module, field_name)

    def can_edit_field(self, module: str, field_name: str) -> bool:
        from app.core.permission_service import PermissionService

        return PermissionService.can_edit_field(self, module, field_name)

    def field_access_level(self, module: str, field_name: str) -> int:
        from app.core.permission_service import PermissionService

        return PermissionService.field_access_level(self, module, field_name)

    @property
    def is_admin(self) -> bool:
        return self.has_role("admin")

    def block(self, blocked_by: uuid.UUID | None = None, reason: str | None = None) -> None:
        """Блокирует пользователя."""
        self.is_blocked = True
        self.blocked_at = utcnow()
        self.blocked_by = blocked_by
        self.block_reason = reason

    def unblock(self) -> None:
        """Разблокирует пользователя."""
        self.is_blocked = False
        self.blocked_at = None
        self.blocked_by = None
        self.block_reason = None

    def __repr__(self) -> str:
        return f"<User {self.email}>"
