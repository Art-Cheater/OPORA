"""Статусы заявок."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel

if TYPE_CHECKING:
    from app.models.requests.request import Request
    from app.models.requests.request_history import RequestHistory


class RequestStatus(ActiveRecordMixin, BaseModel):
    """Справочник статусов заявок."""

    __tablename__ = "request_statuses"
    __table_args__ = (
        Index(
            "ix_request_statuses_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_request_statuses_sort_order", "sort_order"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="#6c757d", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    requests: Mapped[list[Request]] = relationship(
        "Request",
        back_populates="status",
        foreign_keys="Request.status_id",
        lazy="select",
    )
    history_entries: Mapped[list[RequestHistory]] = relationship(
        "RequestHistory",
        back_populates="status",
        foreign_keys="RequestHistory.status_id",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<RequestStatus {self.code}>"
