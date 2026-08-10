"""Справочник диспетчеров для выбора в заявке (не учётные записи)."""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ActiveRecordMixin, BaseModel


class RequestDispatcher(ActiveRecordMixin, BaseModel):
    """ФИО диспетчера, принявшего заявку (общий аккаунт → выбор имени вручную)."""

    __tablename__ = "request_dispatchers"
    __table_args__ = (
        Index(
            "ix_request_dispatchers_name_unique_active",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_request_dispatchers_sort_order", "sort_order"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<RequestDispatcher {self.name}>"
