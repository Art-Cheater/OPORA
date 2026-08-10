"""Вложения к сущностям (полиморфные)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User


class Attachment(BaseModel):
    """Файловое вложение к любой сущности системы."""

    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_entity", "entity_type", "entity_id"),
        Index("ix_attachments_uploaded_by", "uploaded_by"),
        Index("ix_attachments_file_name", "file_name"),
    )

    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)

    uploader: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[uploaded_by],
    )

    def __repr__(self) -> str:
        return f"<Attachment {self.file_name}>"
