"""Путевой лист."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String, Text
from app.models.types import GUID, SearchVectorType
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.waybills.waybill_history import WaybillHistory
    from app.models.waybills.waybill_member import WaybillMember
    from app.models.waybills.waybill_stop import WaybillStop


class Waybill(BaseModel):
    """Путевой лист мастера: набор точек на один выезд."""

    __tablename__ = "waybills"
    __table_args__ = (
        Index("ix_waybills_number", "number", unique=True),
        Index("ix_waybills_master_id", "master_id"),
        Index("ix_waybills_status", "status"),
        Index("ix_waybills_work_date", "work_date"),
        Index("ix_waybills_deleted_created", "deleted_at", "created_at"),
    )

    number: Mapped[str] = mapped_column(String(50), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[str | None] = deferred(
        mapped_column(SearchVectorType, nullable=True)
    )

    master_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    master: Mapped[User] = relationship(
        "User",
        foreign_keys=[master_id],
    )
    stops: Mapped[list[WaybillStop]] = relationship(
        "WaybillStop",
        back_populates="waybill",
        foreign_keys="WaybillStop.waybill_id",
        lazy="select",
        order_by="WaybillStop.sort_order.asc()",
    )
    members: Mapped[list[WaybillMember]] = relationship(
        "WaybillMember",
        back_populates="waybill",
        foreign_keys="WaybillMember.waybill_id",
        lazy="select",
    )
    history: Mapped[list[WaybillHistory]] = relationship(
        "WaybillHistory",
        back_populates="waybill",
        foreign_keys="WaybillHistory.waybill_id",
        lazy="select",
        order_by="WaybillHistory.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Waybill {self.number}>"
