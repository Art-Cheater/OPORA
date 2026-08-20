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
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("messenger_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    card_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    card_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    card_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    card_subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    card_url: Mapped[str | None] = mapped_column(String(700), nullable=True)

    conversation: Mapped[MessengerConversation] = relationship(
        "MessengerConversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )
    sender: Mapped[User] = relationship("User", foreign_keys=[sender_id])
    reply_to: Mapped[MessengerMessage | None] = relationship(
        "MessengerMessage",
        remote_side="MessengerMessage.id",
        foreign_keys=[reply_to_id],
    )

    @property
    def has_attachment(self) -> bool:
        return bool(self.storage_key)

    @property
    def has_card(self) -> bool:
        return bool(self.card_type and self.card_id and self.card_url)

    @property
    def is_image(self) -> bool:
        return bool(self.mime_type and self.mime_type.startswith("image/"))

    def __repr__(self) -> str:
        return f"<MessengerMessage {self.id} conv={self.conversation_id}>"
