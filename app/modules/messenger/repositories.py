"""Репозитории мессенджера."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select

from app.extensions import db
from app.models.auth.user import User
from app.models.base import as_utc_aware, utcnow
from app.models.messenger.messenger_conversation import MessengerConversation
from app.models.messenger.messenger_message import MessengerMessage
from app.models.messenger.user_presence import UserPresence


class MessengerRepository:
    """Доступ к данным мессенджера."""

    @staticmethod
    def get_conversation(conversation_id: uuid.UUID) -> MessengerConversation | None:
        return db.session.scalar(
            select(MessengerConversation).where(
                MessengerConversation.id == conversation_id,
                MessengerConversation.active_filter(),
            )
        )

    @staticmethod
    def user_in_conversation(conversation: MessengerConversation, user_id: uuid.UUID) -> bool:
        return user_id in (conversation.participant_a_id, conversation.participant_b_id)

    @classmethod
    def get_or_create_conversation(
        cls,
        user_id: uuid.UUID,
        peer_id: uuid.UUID,
        *,
        created_by: uuid.UUID,
    ) -> MessengerConversation:
        if user_id == peer_id:
            raise ValueError("Нельзя создать диалог с самим собой.")

        a_id, b_id = MessengerConversation.ordered_pair(user_id, peer_id)
        conversation = db.session.scalar(
            select(MessengerConversation).where(
                MessengerConversation.participant_a_id == a_id,
                MessengerConversation.participant_b_id == b_id,
                MessengerConversation.active_filter(),
            )
        )
        if conversation is not None:
            return conversation

        conversation = MessengerConversation(
            participant_a_id=a_id,
            participant_b_id=b_id,
            created_by=created_by,
            updated_by=created_by,
        )
        db.session.add(conversation)
        db.session.flush()
        return conversation

    @staticmethod
    def list_conversations(user_id: uuid.UUID) -> list[MessengerConversation]:
        stmt = (
            select(MessengerConversation)
            .where(
                MessengerConversation.active_filter(),
                or_(
                    MessengerConversation.participant_a_id == user_id,
                    MessengerConversation.participant_b_id == user_id,
                ),
            )
            .order_by(
                MessengerConversation.last_message_at.desc().nullslast(),
                MessengerConversation.updated_at.desc(),
            )
        )
        return list(db.session.scalars(stmt))

    @staticmethod
    def unread_count_for_conversation(conversation_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return db.session.scalar(
            select(func.count())
            .select_from(MessengerMessage)
            .where(
                MessengerMessage.conversation_id == conversation_id,
                MessengerMessage.sender_id != user_id,
                MessengerMessage.is_read.is_(False),
                MessengerMessage.active_filter(),
            )
        ) or 0

    @staticmethod
    def total_unread_count(user_id: uuid.UUID) -> int:
        return db.session.scalar(
            select(func.count())
            .select_from(MessengerMessage)
            .join(
                MessengerConversation,
                MessengerMessage.conversation_id == MessengerConversation.id,
            )
            .where(
                MessengerMessage.sender_id != user_id,
                MessengerMessage.is_read.is_(False),
                MessengerMessage.active_filter(),
                MessengerConversation.active_filter(),
                or_(
                    MessengerConversation.participant_a_id == user_id,
                    MessengerConversation.participant_b_id == user_id,
                ),
            )
        ) or 0

    @staticmethod
    def list_messages(
        conversation_id: uuid.UUID,
        *,
        before_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[MessengerMessage]:
        stmt = (
            select(MessengerMessage)
            .where(
                MessengerMessage.conversation_id == conversation_id,
                MessengerMessage.active_filter(),
            )
            .order_by(MessengerMessage.created_at.desc())
            .limit(limit)
        )
        if before_id is not None:
            before_msg = db.session.get(MessengerMessage, before_id)
            if before_msg is not None:
                stmt = stmt.where(MessengerMessage.created_at < before_msg.created_at)

        messages = list(db.session.scalars(stmt))
        messages.reverse()
        return messages

    @staticmethod
    def search_messages(user_id: uuid.UUID, query: str, limit: int = 50) -> list[MessengerMessage]:
        q = f"%{query.strip()}%"
        stmt = (
            select(MessengerMessage)
            .join(
                MessengerConversation,
                MessengerMessage.conversation_id == MessengerConversation.id,
            )
            .where(
                MessengerMessage.active_filter(),
                MessengerConversation.active_filter(),
                or_(
                    MessengerConversation.participant_a_id == user_id,
                    MessengerConversation.participant_b_id == user_id,
                ),
                or_(
                    MessengerMessage.body.ilike(q),
                    MessengerMessage.file_name.ilike(q),
                ),
            )
            .order_by(MessengerMessage.created_at.desc())
            .limit(limit)
        )
        return list(db.session.scalars(stmt))

    @staticmethod
    def list_users(current_user_id: uuid.UUID, query: str = "") -> list[User]:
        """Все сотрудники системы (кроме текущего пользователя)."""
        stmt = select(User).where(
            User.active_filter(),
            User.id != current_user_id,
        )
        if query.strip():
            q = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    User.full_name.ilike(q),
                    User.email.ilike(q),
                    User.department.ilike(q),
                    User.position.ilike(q),
                    User.phone.ilike(q),
                )
            )
        stmt = stmt.order_by(User.full_name.asc())
        return list(db.session.scalars(stmt))

    @staticmethod
    def touch_presence(user_id: uuid.UUID) -> UserPresence:
        presence = db.session.scalar(
            select(UserPresence).where(
                UserPresence.user_id == user_id,
                UserPresence.active_filter(),
            )
        )
        now = utcnow()
        if presence is None:
            presence = UserPresence(user_id=user_id, last_seen_at=now, created_by=user_id, updated_by=user_id)
            db.session.add(presence)
        else:
            presence.last_seen_at = now
            presence.updated_by = user_id
        db.session.flush()
        return presence

    @staticmethod
    def is_user_online(user_id: uuid.UUID, timeout_seconds: int) -> bool:
        presence = db.session.scalar(
            select(UserPresence).where(
                UserPresence.user_id == user_id,
                UserPresence.active_filter(),
            )
        )
        if presence is None:
            return False
        last_seen = as_utc_aware(presence.last_seen_at)
        if last_seen is None:
            return False
        delta = utcnow() - last_seen
        return delta.total_seconds() <= timeout_seconds

    @staticmethod
    def online_status_map(user_ids: list[uuid.UUID], timeout_seconds: int) -> dict[str, bool]:
        if not user_ids:
            return {}
        presences = db.session.scalars(
            select(UserPresence).where(
                UserPresence.user_id.in_(user_ids),
                UserPresence.active_filter(),
            )
        )
        now = utcnow()
        result: dict[str, bool] = {str(uid): False for uid in user_ids}
        for presence in presences:
            last_seen = as_utc_aware(presence.last_seen_at)
            if last_seen is None:
                continue
            delta = now - last_seen
            result[str(presence.user_id)] = delta.total_seconds() <= timeout_seconds
        return result
