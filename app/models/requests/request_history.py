"""История изменений заявки."""

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
    from app.models.requests.request import Request
    from app.models.requests.request_status import RequestStatus


class RequestHistory(BaseModel):
    """История изменений заявки."""

    __tablename__ = "request_history"
    __table_args__ = (
        Index("ix_request_history_request_id", "request_id"),
        Index("ix_request_history_status_id", "status_id"),
        Index("ix_request_history_changed_by", "changed_by"),
        Index("ix_request_history_status_created", "status_id", "created_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    status_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("request_statuses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_status_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("request_statuses.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="update")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    request: Mapped[Request] = relationship(
        "Request",
        back_populates="history",
        foreign_keys=[request_id],
    )
    status: Mapped[RequestStatus] = relationship(
        "RequestStatus",
        back_populates="history_entries",
        foreign_keys=[status_id],
    )
    previous_status: Mapped[RequestStatus | None] = relationship(
        "RequestStatus",
        foreign_keys=[previous_status_id],
    )
    changed_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[changed_by],
    )

    def __repr__(self) -> str:
        return f"<RequestHistory request={self.request_id} status={self.status_id}>"
