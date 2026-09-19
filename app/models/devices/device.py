"""Inventory and observed state of a TCP-connected controller."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from app.models.types import JSONType


class Device(BaseModel):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_connection_state", "connection_state"),)

    device_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Encrypted server-side material, never a plain secret and never returned by UI/API.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    protocol_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    connection_state: Mapped[str] = mapped_column(String(24), nullable=False, default="offline")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    actual_state: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    desired_state: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    telemetry: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    last_state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
