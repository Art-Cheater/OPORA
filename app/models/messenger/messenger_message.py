"""Сообщение мессенджера."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.messenger.messenger_conversation import MessengerConversation


class MessengerMessage(BaseModel):
    """Сообщение в личном диалоге."""

    __tablename__ = "messenger_messages"
    __table_args__ = (
        Index("ix_messenger_messages_conversation_id", "conversation_id"),
        Index("ix_messenger_messages_sender_id", "sender_id"),
        Index("ix_messenger_messages_is_read", "is_read"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("messenger_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    conversation: Mapped[MessengerConversation] = relationship(
        "MessengerConversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )
    sender: Mapped[User] = relationship("User", foreign_keys=[sender_id])

    @property
    def has_attachment(self) -> bool:
        return bool(self.storage_key)

    def __repr__(self) -> str:
        return f"<MessengerMessage {self.id} conv={self.conversation_id}>"
