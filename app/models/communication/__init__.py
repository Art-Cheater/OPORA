"""Модели коммуникаций."""

from app.models.communication.comment import Comment
from app.models.communication.message import Message
from app.models.communication.notification import Notification

__all__ = ["Message", "Notification", "Comment"]
