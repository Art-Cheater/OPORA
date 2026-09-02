"""Точка маршрута путевого листа."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.defects.defect import Defect
    from app.models.requests.request import Request
    from app.models.waybills.waybill import Waybill


class WaybillStop(BaseModel):
    """Одна работа в маршруте: заявка или дефект."""

    __tablename__ = "waybill_stops"
    __table_args__ = (
        Index(
            "uq_waybill_stops_order",
            "waybill_id",
            "sort_order",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "(request_id IS NOT NULL AND defect_id IS NULL) "
            "OR (request_id IS NULL AND defect_id IS NOT NULL)",
            name="ck_waybill_stops_one_target",
        ),
        Index("ix_waybill_stops_waybill_id", "waybill_id"),
        Index("ix_waybill_stops_request_id", "request_id"),
        Index("ix_waybill_stops_defect_id", "defect_id"),
    )

    waybill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("waybills.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=True,
    )
    defect_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("defects.id", ondelete="CASCADE"),
        nullable=True,
    )
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    waybill: Mapped[Waybill] = relationship(
        "Waybill",
        back_populates="stops",
        foreign_keys=[waybill_id],
    )
    request: Mapped[Request | None] = relationship(
        "Request",
        foreign_keys=[request_id],
    )
    defect: Mapped[Defect | None] = relationship(
        "Defect",
        foreign_keys=[defect_id],
    )
