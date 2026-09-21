"""Persisted raw ATM21 traffic for the IRZ engineering console."""

from sqlalchemy import CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class IRZExchangeLog(BaseModel):
    __tablename__ = "irz_exchange_logs"
    __table_args__ = (
        CheckConstraint("direction IN ('RX', 'TX')", name="ck_irz_exchange_logs_direction"),
        Index("ix_irz_exchange_logs_imei_created", "imei", "created_at"),
    )

    imei: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    direction: Mapped[str] = mapped_column(String(2), nullable=False)
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False)
    raw_ascii: Mapped[str] = mapped_column(Text, nullable=False)
    raw_length: Mapped[int] = mapped_column(Integer, nullable=False)
