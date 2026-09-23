"""Persisted raw ATM21 traffic for the IRZ engineering console."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel
from app.models.types import GUID, JSONType


class IRZDevice(BaseModel):
    __tablename__ = "irz_devices"
    __table_args__ = (
        Index("ix_irz_devices_enabled_name", "enabled", "name"),
    )

    imei: Mapped[str | None] = mapped_column(String(15), nullable=True, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    model: Mapped[str] = mapped_column(String(40), nullable=False, default="ATM21")
    serial_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    network_address: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transport_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    firmware_revision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    firmware_build: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hardware_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sim: Mapped[str | None] = mapped_column(String(40), nullable=True)
    csq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    atp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    interfaces: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_manufacture_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    last_firmware_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_transformation_ratios: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    last_mercury_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    poll_lock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class IRZMeter(BaseModel):
    """A Mercury meter physically discovered behind an ATM21 session."""
    __tablename__ = "irz_meters"
    __table_args__ = (
        Index("ix_irz_meters_device_seen", "irz_device_id", "last_seen_at"),
    )

    irz_device_id: Mapped[Any] = mapped_column(
        GUID(), ForeignKey("irz_devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    serial_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    custom_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    manufacture_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_poll_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latest_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


class IRZMeterSnapshot(BaseModel):
    """One logical poll result; JSON avoids a row per individual measurement."""
    __tablename__ = "irz_meter_snapshots"
    __table_args__ = (
        Index("ix_irz_meter_snapshots_meter_captured", "meter_id", "captured_at"),
        Index("ix_irz_meter_snapshots_captured", "captured_at"),
    )

    meter_id: Mapped[Any] = mapped_column(GUID(), ForeignKey("irz_meters.id", ondelete="CASCADE"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    quality: Mapped[str] = mapped_column(String(20), nullable=False)
    quality_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    poll_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS")
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


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
    packet_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)


class IRZExperiment(BaseModel):
    __tablename__ = "irz_experiments"
    __table_args__ = (Index("ix_irz_experiments_imei_created", "imei", "created_at"),)

    imei: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    command_hex: Mapped[str] = mapped_column(Text, nullable=False)
    response_hex: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_ascii: Mapped[str] = mapped_column(Text, nullable=False, default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
