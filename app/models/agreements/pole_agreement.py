"""Договор на размещение оборудования на опорах НО."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.agreements.pole_agreement_site import PoleAgreementSite
    from app.models.auth.user import User


class PoleAgreement(ActiveRecordMixin, BaseModel):
    __tablename__ = "pole_agreements"
    __table_args__ = (
        Index("ix_pole_agreements_customer_name", "customer_name"),
        Index("ix_pole_agreements_deleted_created", "deleted_at", "created_at"),
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    customer_inn: Mapped[str | None] = mapped_column(String(12), nullable=True)
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(700), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    sites: Mapped[list[PoleAgreementSite]] = relationship(
        "PoleAgreementSite",
        back_populates="agreement",
        foreign_keys="PoleAgreementSite.agreement_id",
        lazy="select",
        cascade="all, delete-orphan",
        order_by="PoleAgreementSite.sort_order",
    )
    uploader: Mapped[User | None] = relationship("User", foreign_keys=[uploaded_by])

    def __repr__(self) -> str:
        return f"<PoleAgreement {self.number or self.title[:40]}>"
