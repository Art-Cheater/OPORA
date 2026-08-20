"""Строка адресной программы договора на опорах."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID, JSONType

if TYPE_CHECKING:
    from app.models.agreements.pole_agreement import PoleAgreement


class PoleAgreementSite(BaseModel):
    __tablename__ = "pole_agreement_sites"
    __table_args__ = (
        Index("ix_pole_agreement_sites_agreement_id", "agreement_id"),
        Index("ix_pole_agreement_sites_address_norm", "address_norm"),
    )

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("pole_agreements.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str] = mapped_column(String(2000), nullable=False)
    address_norm: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    mounts_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poles_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)

    agreement: Mapped[PoleAgreement] = relationship(
        "PoleAgreement",
        back_populates="sites",
        foreign_keys=[agreement_id],
    )

    def __repr__(self) -> str:
        return f"<PoleAgreementSite {self.address[:40]}>"
