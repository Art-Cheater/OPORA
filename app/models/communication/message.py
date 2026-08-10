"""Внутренние сообщения."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User


class Message(BaseModel):
    """Внутреннее сообщение между пользователями."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_sender_id", "sender_id"),
        Index("ix_messages_recipient_id", "recipient_id"),
        Index("ix_messages_parent_id", "parent_id"),
        Index("ix_messages_is_read", "is_read"),
    )

    sender_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)

    sender: Mapped[User] = relationship(
        "User",
        foreign_keys=[sender_id],
    )
    recipient: Mapped[User] = relationship(
        "User",
        foreign_keys=[recipient_id],
    )
    parent: Mapped[Message | None] = relationship(
        "Message",
        remote_side="Message.id",
        foreign_keys=[parent_id],
    )
    replies: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="parent",
        foreign_keys=[parent_id],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Message {self.id} from={self.sender_id}>"
