"""Сериализация данных мессенджера для API."""

from __future__ import annotations

import uuid
from datetime import datetime

from flask import url_for

from app.models.auth.user import User
from app.models.messenger.messenger_conversation import MessengerConversation
from app.models.messenger.messenger_message import MessengerMessage
from app.modules.messenger.repositories import MessengerRepository


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def serialize_user(
    user: User,
    *,
    online: bool | None = None,
    current_user_id: uuid.UUID | None = None,
) -> dict:
    data = {
        "id": str(user.id),
        "full_name": user.full_name,
        "email": user.email,
        "department": user.department,
        "position": user.position,
        "role_names": user.role_names,
        "is_active": user.is_active,
        "is_blocked": user.is_blocked,
        "initial": user.full_name[0].upper() if user.full_name else "?",
    }
    if online is not None:
        data["is_online"] = online
    if current_user_id is not None:
        data["is_self"] = user.id == current_user_id
    return data


def serialize_message(message: MessengerMessage, current_user_id: uuid.UUID) -> dict:
    data = {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "sender_id": str(message.sender_id),
        "body": message.body,
        "is_mine": message.sender_id == current_user_id,
        "is_read": message.is_read,
        "read_at": _iso(message.read_at),
        "created_at": _iso(message.created_at),
        "has_attachment": message.has_attachment,
    }
    if message.has_attachment:
        data["file"] = {
            "name": message.file_name,
            "mime_type": message.mime_type,
            "size": message.file_size,
            "url": url_for(
                "messenger.download_file",
                message_id=message.id,
                _external=False,
            ),
        }
    return data


def serialize_conversation(
    conversation: MessengerConversation,
    current_user_id: uuid.UUID,
    *,
    online_map: dict[str, bool] | None = None,
) -> dict:
    peer = conversation.other_user(current_user_id)
    peer_id = conversation.other_user_id(current_user_id)
    online = (online_map or {}).get(str(peer_id), False)
    unread = MessengerRepository.unread_count_for_conversation(conversation.id, current_user_id)
    return {
        "id": str(conversation.id),
        "peer": serialize_user(peer, online=online),
        "last_message_preview": conversation.last_message_preview,
        "last_message_at": _iso(conversation.last_message_at),
        "unread_count": unread,
    }


def serialize_search_result(message: MessengerMessage, current_user_id: uuid.UUID) -> dict:
    conversation = message.conversation
    peer = conversation.other_user(current_user_id)
    return {
        "message": serialize_message(message, current_user_id),
        "conversation_id": str(conversation.id),
        "peer": serialize_user(peer),
    }
