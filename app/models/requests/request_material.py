"""Использованные материалы в заявке."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.requests.request import Request


class RequestMaterial(BaseModel):
    """Материал, использованный при выполнении заявки."""

    __tablename__ = "request_materials"
    __table_args__ = (
        Index("ix_request_materials_request_id", "request_id"),
        Index("ix_request_materials_name", "name"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="шт")
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    request: Mapped[Request] = relationship(
        "Request",
        back_populates="materials",
        foreign_keys=[request_id],
    )

    def __repr__(self) -> str:
        return f"<RequestMaterial {self.name} x {self.quantity}>"
