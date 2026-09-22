"""Persisted raw ATM21 traffic for the IRZ engineering console."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from app.models.types import GUID, JSONType


class IRZDevice(BaseModel):
    __tablename__ = "irz_devices"
    __table_args__ = (
        CheckConstraint("transport_type IN ('SERIAL', 'TCP')", name="ck_irz_devices_transport"),
        CheckConstraint("connection_state IN ('DISCONNECTED', 'CONNECTING', 'CONNECTED', 'BUSY', 'ERROR')", name="ck_irz_devices_state"),
        Index("ix_irz_devices_enabled_name", "enabled", "name"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    model: Mapped[str] = mapped_column(String(40), nullable=False, default="Mercury V2")
    serial_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    network_address: Mapped[int] = mapped_column(Integer, nullable=False)
    transport_type: Mapped[str] = mapped_column(String(10), nullable=False)
    serial_port: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host: Mapped[str | None] = mapped_column(String(253), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baudrate: Mapped[int] = mapped_column(Integer, nullable=False, default=9600)
    connection_params: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    connection_state: Mapped[str] = mapped_column(String(16), nullable=False, default="DISCONNECTED", index=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IRZOperationLog(BaseModel):
    __tablename__ = "irz_operation_logs"
    __table_args__ = (
        CheckConstraint("status IN ('SUCCESS', 'ERROR', 'TIMEOUT')", name="ck_irz_operation_logs_status"),
        Index("ix_irz_operation_logs_device_created", "device_id", "created_at"),
        Index("ix_irz_operation_logs_status_created", "status", "created_at"),
    )

    device_id: Mapped[Any] = mapped_column(GUID(), ForeignKey("irz_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[Any | None] = mapped_column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    command_id: Mapped[str] = mapped_column(String(80), nullable=False)
    mercury_command: Mapped[str | None] = mapped_column(String(120), nullable=True)
    operation: Mapped[str] = mapped_column(String(20), nullable=False, default="COMMAND")
    request_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    result: Mapped[dict[str, Any] | list[Any] | str | int | float | bool | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tx_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    rx_raw: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class IRZExperiment(BaseModel):
    __tablename__ = "irz_experiments"
    __table_args__ = (Index("ix_irz_experiments_imei_created", "imei", "created_at"),)

    imei: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    command_hex: Mapped[str] = mapped_column(Text, nullable=False)
    response_hex: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_ascii: Mapped[str] = mapped_column(Text, nullable=False, default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
