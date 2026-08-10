"""Комментарии к сущностям (полиморфные)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User


class Comment(BaseModel):
    """Комментарий к любой сущности системы."""

    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_entity", "entity_type", "entity_id"),
        Index("ix_comments_author_id", "author_id"),
        Index("ix_comments_parent_id", "parent_id"),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("comments.id", ondelete="SET NULL"),
        nullable=True,
    )

    author: Mapped[User] = relationship(
        "User",
        foreign_keys=[author_id],
    )
    parent: Mapped[Comment | None] = relationship(
        "Comment",
        remote_side="Comment.id",
        foreign_keys=[parent_id],
    )
    replies: Mapped[list[Comment]] = relationship(
        "Comment",
        back_populates="parent",
        foreign_keys=[parent_id],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Comment {self.id} entity={self.entity_type}:{self.entity_id}>"
