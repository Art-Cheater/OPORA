"""История путевого листа."""

from __future__ import annotations

import uuid
from typing import Any
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from app.models.types import GUID, JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.waybills.waybill import Waybill


class WaybillHistory(BaseModel):
    """История изменений путевого листа."""

    __tablename__ = "waybill_history"
    __table_args__ = (
        Index("ix_waybill_history_waybill_id", "waybill_id"),
        Index("ix_waybill_history_changed_by", "changed_by"),
    )

    waybill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("waybills.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="update")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    waybill: Mapped[Waybill] = relationship(
        "Waybill",
        back_populates="history",
        foreign_keys=[waybill_id],
    )
    changed_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[changed_by],
    )
