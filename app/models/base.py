"""Базовая модель и миксины для всех сущностей системы «Опора»."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

if TYPE_CHECKING:
    from app.models.auth.user import User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc_aware(dt: datetime | None) -> datetime | None:
    """Приводит datetime к UTC-aware (SQLite часто возвращает naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class BaseModel(db.Model):
    """Абстрактная базовая модель с UUID, аудитом и soft delete."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_%(table_name)s_created_by_users"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_%(table_name)s_updated_by_users"),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, deleted_by: uuid.UUID | None = None) -> None:
        """Мягкое удаление записи."""
        self.deleted_at = utcnow()
        if deleted_by is not None:
            self.updated_by = deleted_by

    def restore(self) -> None:
        """Восстановление мягко удалённой записи."""
        self.deleted_at = None

    @classmethod
    def active_filter(cls):
        """Условие для выборки только активных (не удалённых) записей."""
        return cls.deleted_at.is_(None)


class ActiveRecordMixin:
    """Миксин: флаг активности записи."""

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

