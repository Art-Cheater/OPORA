"""Temporary field diagnostics captured only while a device opts in."""
from __future__ import annotations
import uuid
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import BaseModel
from app.models.types import GUID, JSONType


class DeviceDiagnosticSample(BaseModel):
    __tablename__ = "device_diagnostic_samples"
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    outputs_mask: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_u2: Mapped[str | None] = mapped_column(String(2), nullable=True)
    raw_u3: Mapped[str | None] = mapped_column(String(2), nullable=True)
    csq: Mapped[str | None] = mapped_column(String(32), nullable=True)
    creg: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cgatt: Mapped[str | None] = mapped_column(String(32), nullable=True)


class DeviceInputTestLog(BaseModel):
    __tablename__ = "device_input_test_logs"
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    connector: Mapped[str] = mapped_column(String(8), nullable=False)
    pin: Mapped[str] = mapped_column(String(1), nullable=False)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ended_at: Mapped[str] = mapped_column(String(40), nullable=False)
    start_u2: Mapped[str | None] = mapped_column(String(2), nullable=True)
    start_u3: Mapped[str | None] = mapped_column(String(2), nullable=True)
    end_u2: Mapped[str | None] = mapped_column(String(2), nullable=True)
    end_u3: Mapped[str | None] = mapped_column(String(2), nullable=True)
    changed_bits: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    transitions: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class DeviceDiagnosticEvent(BaseModel):
    __tablename__ = "device_diagnostic_events"
    device_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
