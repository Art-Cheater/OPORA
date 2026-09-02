"""Исполнители путевого листа."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.waybills.waybill import Waybill


class WaybillMember(BaseModel):
    """Участник бригады в путевом листе."""

    __tablename__ = "waybill_members"
    __table_args__ = (
        Index(
            "uq_waybill_members_user",
            "waybill_id",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_waybill_members_waybill_id", "waybill_id"),
        Index("ix_waybill_members_user_id", "user_id"),
    )

    waybill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("waybills.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    waybill: Mapped[Waybill] = relationship(
        "Waybill",
        back_populates="members",
        foreign_keys=[waybill_id],
    )
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
    )
