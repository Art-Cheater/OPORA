"""Журнал аудита действий пользователей."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from app.models.types import GUID, JSONType, SearchVectorType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import AuditAction


class AuditLogImmutableError(PermissionError):
    """Запись журнала аудита не может быть изменена или удалена."""


class AuditLog(BaseModel):
    """Запись журнала аудита. Неизменяемая — удаление запрещено."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_user_id", "user_id"),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=AuditAction.CREATE.value,
    )
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[str | None] = mapped_column(SearchVectorType, nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    def soft_delete(self, deleted_by: uuid.UUID | None = None) -> None:
        raise AuditLogImmutableError("Записи журнала действий не могут быть удалены.")

    def restore(self) -> None:
        raise AuditLogImmutableError("Записи журнала действий не могут быть изменены.")

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}:{self.entity_id}>"
