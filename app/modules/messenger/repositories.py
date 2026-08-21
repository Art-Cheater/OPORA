"""Репозитории мессенджера."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased, contains_eager, joinedload, selectinload

from app.extensions import db
from app.models.auth.associations import UserRole
from app.models.auth.role import Role
from app.models.auth.user import User
from app.models.base import as_utc_aware, utcnow
from app.models.messenger.messenger_conversation import MessengerConversation
from app.models.messenger.messenger_message import MessengerMessage
from app.models.messenger.user_presence import UserPresence


class MessengerRepository:
    """Доступ к данным мессенджера."""

    @staticmethod
    def _conversation_options():
        return (
            joinedload(MessengerConversation.participant_a)
            .selectinload(User.user_roles)
            .joinedload(UserRole.role)
            .lazyload(Role.role_permissions),
            joinedload(MessengerConversation.participant_b)
            .selectinload(User.user_roles)
            .joinedload(UserRole.role)
            .lazyload(Role.role_permissions),
        )

    @staticmethod
    def get_conversation(conversation_id: uuid.UUID) -> MessengerConversation | None:
        return db.session.scalar(
            select(MessengerConversation)
            .options(*MessengerRepository._conversation_options())
            .where(
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
            select(MessengerConversation)
            .options(*cls._conversation_options())
            .where(
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
            .options(*MessengerRepository._conversation_options())
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
    def search_conversations(user_id: uuid.UUID, query: str, limit: int = 20) -> list[MessengerConversation]:
        """Чаты текущего пользователя по имени собеседника или тексту последнего сообщения."""
        needle = query.strip()
        if len(needle) < 2:
            return []
        q = f"%{needle}%"
        peer = aliased(User)
        stmt = (
            select(MessengerConversation)
            .options(*MessengerRepository._conversation_options())
            .join(
                peer,
                or_(
                    and_(
                        MessengerConversation.participant_a_id == user_id,
                        MessengerConversation.participant_b_id == peer.id,
                    ),
                    and_(
                        MessengerConversation.participant_b_id == user_id,
                        MessengerConversation.participant_a_id == peer.id,
                    ),
                ),
            )
            .where(
                MessengerConversation.active_filter(),
                or_(
                    peer.full_name.ilike(q),
                    peer.email.ilike(q),
                    peer.department.ilike(q),
                    peer.position.ilike(q),
                    MessengerConversation.last_message_preview.ilike(q),
                ),
            )
            .order_by(
                MessengerConversation.last_message_at.desc().nullslast(),
                MessengerConversation.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 50)))
        )
        return list(db.session.scalars(stmt).unique())

    @staticmethod
    def unread_counts_for_conversations(
        conversation_ids: list[uuid.UUID],
        user_id: uuid.UUID,
    ) -> dict[uuid.UUID, int]:
        """Aggregate unread counts for a conversation list in one query."""
        if not conversation_ids:
            return {}
        rows = db.session.execute(
            select(
                MessengerMessage.conversation_id,
                func.count(MessengerMessage.id),
            )
            .where(
                MessengerMessage.conversation_id.in_(conversation_ids),
                MessengerMessage.sender_id != user_id,
                MessengerMessage.is_read.is_(False),
                MessengerMessage.active_filter(),
            )
            .group_by(MessengerMessage.conversation_id)
        )
        return {conversation_id: int(count) for conversation_id, count in rows}

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
    def latest_unread_preview(user_id: uuid.UUID) -> dict | None:
        """Краткое превью последнего непрочитанного входящего сообщения."""
        stmt = (
            select(MessengerMessage)
            .options(
                contains_eager(MessengerMessage.conversation)
                .joinedload(MessengerConversation.participant_a)
                .lazyload(User.user_roles),
                contains_eager(MessengerMessage.conversation)
                .joinedload(MessengerConversation.participant_b)
                .lazyload(User.user_roles),
            )
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
            .order_by(MessengerMessage.created_at.desc())
            .limit(1)
        )
        message = db.session.scalar(stmt)
        if message is None:
            return None
        conversation = message.conversation
        peer = conversation.other_user(user_id)
        body = (message.body or "").strip()
        if not body and message.card_title:
            body = message.card_title
        if not body and message.file_name:
            body = f"📎 {message.file_name}"
        if not body:
            body = "Новое сообщение"
        if len(body) > 140:
            body = body[:140] + "…"
        return {
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "peer_name": peer.full_name if peer else "Собеседник",
            "body": body,
        }

    @staticmethod
    def get_message(message_id: uuid.UUID) -> MessengerMessage | None:
        return db.session.scalar(
            select(MessengerMessage)
            .options(
                joinedload(MessengerMessage.reply_to)
                .joinedload(MessengerMessage.sender)
                .lazyload(User.user_roles),
                joinedload(MessengerMessage.sender).lazyload(User.user_roles),
            )
            .where(
                MessengerMessage.id == message_id,
                MessengerMessage.active_filter(),
            )
        )

    @staticmethod
    def list_messages(
        conversation_id: uuid.UUID,
        *,
        before_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[MessengerMessage]:
        stmt = (
            select(MessengerMessage)
            .options(
                joinedload(MessengerMessage.reply_to)
                .joinedload(MessengerMessage.sender)
                .lazyload(User.user_roles),
                joinedload(MessengerMessage.sender).lazyload(User.user_roles),
            )
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

        messages = list(db.session.scalars(stmt).unique())
        messages.reverse()
        return messages

    @staticmethod
    def search_messages(user_id: uuid.UUID, query: str, limit: int = 50) -> list[MessengerMessage]:
        q = f"%{query.strip()}%"
        stmt = (
            select(MessengerMessage)
            .options(
                joinedload(MessengerMessage.reply_to)
                .joinedload(MessengerMessage.sender)
                .lazyload(User.user_roles),
                joinedload(MessengerMessage.sender).lazyload(User.user_roles),
                contains_eager(MessengerMessage.conversation)
                .joinedload(MessengerConversation.participant_a)
                .selectinload(User.user_roles)
                .joinedload(UserRole.role)
                .lazyload(Role.role_permissions),
                contains_eager(MessengerMessage.conversation)
                .joinedload(MessengerConversation.participant_b)
                .selectinload(User.user_roles)
                .joinedload(UserRole.role)
                .lazyload(Role.role_permissions),
            )
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
                    MessengerMessage.card_title.ilike(q),
                ),
            )
            .order_by(MessengerMessage.created_at.desc())
            .limit(limit)
        )
        return list(db.session.scalars(stmt).unique())

    @staticmethod
    def list_users(
        current_user_id: uuid.UUID,
        query: str = "",
        *,
        limit: int = 50,
    ) -> list[User]:
        """Bounded employee lookup excluding the current user."""
        limit = max(1, min(int(limit), 100))
        stmt = (
            select(User)
            .options(
                selectinload(User.user_roles)
                .joinedload(UserRole.role)
                .lazyload(Role.role_permissions)
            )
            .where(
                User.active_filter(),
                User.id != current_user_id,
            )
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
        stmt = stmt.order_by(User.full_name.asc()).limit(limit)
        return list(db.session.scalars(stmt))

    @staticmethod
    def touch_presence(user_id: uuid.UUID, min_interval_seconds: int = 20) -> UserPresence:
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
            last_seen = as_utc_aware(presence.last_seen_at)
            if last_seen is not None and (now - last_seen).total_seconds() < min_interval_seconds:
                return presence
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
        presence = MessengerRepository.presence_map(user_ids, timeout_seconds)
        return {uid: info["is_online"] for uid, info in presence.items()}

    @staticmethod
    def presence_map(
        user_ids: list[uuid.UUID],
        timeout_seconds: int,
    ) -> dict[str, dict]:
        """Статус присутствия: is_online + last_seen_at (ISO)."""
        if not user_ids:
            return {}
        presences = db.session.scalars(
            select(UserPresence).where(
                UserPresence.user_id.in_(user_ids),
                UserPresence.active_filter(),
            )
        )
        now = utcnow()
        result: dict[str, dict] = {
            str(uid): {"is_online": False, "last_seen_at": None} for uid in user_ids
        }
        for presence in presences:
            last_seen = as_utc_aware(presence.last_seen_at)
            if last_seen is None:
                continue
            delta = now - last_seen
            result[str(presence.user_id)] = {
                "is_online": delta.total_seconds() <= timeout_seconds,
                "last_seen_at": last_seen.isoformat(),
            }
        return result
