"""Сервисы мессенджера."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from app.core.exceptions import NotFoundError, ValidationError
from app.extensions import db
from app.models.messenger.messenger_conversation import MessengerConversation
from app.models.messenger.messenger_message import MessengerMessage
from app.modules.messenger.repositories import MessengerRepository


class MessengerService:
    """Бизнес-логика корпоративного мессенджера."""

    @staticmethod
    def _preview(body: str | None, file_name: str | None) -> str:
        if body and body.strip():
            text = body.strip()
            return text[:200] + ("…" if len(text) > 200 else "")
        if file_name:
            return f"📎 {file_name}"
        return "Сообщение"

    @classmethod
    def ensure_access(cls, conversation_id: uuid.UUID, user_id: uuid.UUID) -> MessengerConversation:
        conversation = MessengerRepository.get_conversation(conversation_id)
        if conversation is None or not MessengerRepository.user_in_conversation(conversation, user_id):
            raise NotFoundError("Диалог не найден.")
        return conversation

    @classmethod
    def send_message(
        cls,
        conversation: MessengerConversation,
        *,
        sender_id: uuid.UUID,
        body: str | None,
        reply_to_id: uuid.UUID | None = None,
    ) -> MessengerMessage:
        body = (body or "").strip()
        if not body:
            raise ValidationError("Текст сообщения не может быть пустым.")

        reply_to = None
        if reply_to_id is not None:
            reply_to = MessengerRepository.get_message(reply_to_id)
            if (
                reply_to is None
                or reply_to.conversation_id != conversation.id
            ):
                raise ValidationError("Сообщение для ответа не найдено.")

        message = MessengerMessage(
            conversation_id=conversation.id,
            sender_id=sender_id,
            body=body,
            reply_to_id=reply_to.id if reply_to else None,
            created_by=sender_id,
            updated_by=sender_id,
        )
        db.session.add(message)
        conversation.last_message_at = datetime.now(timezone.utc)
        conversation.last_message_preview = cls._preview(body, None)
        conversation.updated_by = sender_id
        db.session.commit()
        return MessengerRepository.get_message(message.id) or message

    @classmethod
    def send_file(
        cls,
        conversation: MessengerConversation,
        *,
        sender_id: uuid.UUID,
        file_storage,
        reply_to_id: uuid.UUID | None = None,
    ) -> MessengerMessage:
        from app.core.upload_utils import UploadValidationError, save_upload

        try:
            saved = save_upload(
                file_storage, relative_dir=f"messenger/{conversation.id}"
            )
        except UploadValidationError as exc:
            raise ValidationError(str(exc)) from exc

        reply_to = None
        if reply_to_id is not None:
            reply_to = MessengerRepository.get_message(reply_to_id)
            if (
                reply_to is None
                or reply_to.conversation_id != conversation.id
            ):
                raise ValidationError("Сообщение для ответа не найдено.")

        message = MessengerMessage(
            conversation_id=conversation.id,
            sender_id=sender_id,
            body=None,
            file_name=saved.file_name,
            storage_key=saved.storage_key,
            mime_type=saved.mime_type,
            file_size=saved.file_size,
            reply_to_id=reply_to.id if reply_to else None,
            created_by=sender_id,
            updated_by=sender_id,
        )
        db.session.add(message)
        conversation.last_message_at = datetime.now(timezone.utc)
        conversation.last_message_preview = cls._preview(None, saved.file_name)
        conversation.updated_by = sender_id
        db.session.commit()
        return MessengerRepository.get_message(message.id) or message

    @classmethod
    def mark_read(cls, conversation: MessengerConversation, user_id: uuid.UUID) -> int:
        now = datetime.now(timezone.utc)
        messages = db.session.scalars(
            db.select(MessengerMessage).where(
                MessengerMessage.conversation_id == conversation.id,
                MessengerMessage.sender_id != user_id,
                MessengerMessage.is_read.is_(False),
                MessengerMessage.active_filter(),
            )
        )
        count = 0
        for message in messages:
            message.is_read = True
            message.read_at = now
            message.updated_by = user_id
            count += 1
        if count:
            db.session.commit()
        return count

    @staticmethod
    def get_file_path(message: MessengerMessage) -> Path:
        if not message.storage_key:
            raise NotFoundError("Файл не найден.")
        path = current_app.config["UPLOAD_FOLDER"] / message.storage_key
        if not path.exists():
            raise NotFoundError("Файл не найден.")
        return path

    @staticmethod
    def heartbeat(user_id: uuid.UUID) -> None:
        MessengerRepository.touch_presence(user_id)
        db.session.commit()
