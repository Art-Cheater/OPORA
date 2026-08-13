"""Диалог мессенджера (личная переписка)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, utcnow

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.messenger.messenger_message import MessengerMessage


class MessengerConversation(BaseModel):
    """Личный диалог между двумя пользователями."""

    __tablename__ = "messenger_conversations"
    __table_args__ = (
        Index("ix_messenger_conversations_participant_a", "participant_a_id"),
        Index("ix_messenger_conversations_participant_b", "participant_b_id"),
        Index("ix_messenger_conversations_last_message_at", "last_message_at"),
        Index(
            "ix_messenger_conversations_unique_pair",
            "participant_a_id",
            "participant_b_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    participant_a_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_b_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)

    participant_a: Mapped[User] = relationship("User", foreign_keys=[participant_a_id])
    participant_b: Mapped[User] = relationship("User", foreign_keys=[participant_b_id])
    messages: Mapped[list[MessengerMessage]] = relationship(
        "MessengerMessage",
        back_populates="conversation",
        foreign_keys="MessengerMessage.conversation_id",
        # История загружается только через постраничный запрос репозитория.
        # Это защищает списки диалогов от случайной загрузки всех сообщений.
        lazy="raise",
        order_by="MessengerMessage.created_at.asc()",
    )

    def other_user_id(self, user_id: uuid.UUID) -> uuid.UUID:
        return self.participant_b_id if self.participant_a_id == user_id else self.participant_a_id

    def other_user(self, user_id: uuid.UUID) -> User:
        return self.participant_b if self.participant_a_id == user_id else self.participant_a

    @staticmethod
    def ordered_pair(user1_id: uuid.UUID, user2_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
        if str(user1_id) < str(user2_id):
            return user1_id, user2_id
        return user2_id, user1_id

    def __repr__(self) -> str:
        return f"<MessengerConversation {self.participant_a_id} <-> {self.participant_b_id}>"
