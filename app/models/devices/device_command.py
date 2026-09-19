"""Durable commands sent by the TCP gateway."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from app.models.types import GUID, JSONType


class DeviceCommand(BaseModel):
    __tablename__ = "device_commands"
    __table_args__ = (
        Index("ix_device_commands_device_status", "device_id", "status"),
        Index(
            "uq_device_commands_one_active_per_device",
            "device_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL AND (status IN ('pending', 'sent') OR (status = 'acknowledged' AND state_confirmed_at IS NULL))"),
            postgresql_where=text("deleted_at IS NULL AND (status IN ('pending', 'sent') OR (status = 'acknowledged' AND state_confirmed_at IS NULL))"),
        ),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    command_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
