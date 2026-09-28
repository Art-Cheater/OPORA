"""Small, shared lifecycle helpers for controller command confirmation."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from flask import current_app

from app.extensions import db
from app.models.base import utcnow
from app.models.devices import Device, DeviceCommand
from app.models.devices.state import payload_matches_actual


def active_command_query(device_id: UUID):
    """Return the one command that still owns a controller's command slot."""
    return db.select(DeviceCommand).where(
        DeviceCommand.device_id == device_id,
        DeviceCommand.active_filter(),
        (
            DeviceCommand.status.in_(("pending", "sent"))
            | ((DeviceCommand.status == "acknowledged") & DeviceCommand.state_confirmed_at.is_(None))
        ),
    ).order_by(DeviceCommand.created_at.desc())


def expire_state_confirmation_timeouts(*, device_id: UUID | None = None) -> int:
    """Fail ACKed commands that never received a confirming hardware state."""
    timeout = int(current_app.config["DEVICE_STATE_CONFIRM_TIMEOUT_SECONDS"])
    deadline = utcnow() - timedelta(seconds=timeout)
    query = db.select(DeviceCommand).where(
        DeviceCommand.status == "acknowledged",
        DeviceCommand.state_confirmed_at.is_(None),
        DeviceCommand.acknowledged_at.is_not(None),
        DeviceCommand.acknowledged_at < deadline,
        DeviceCommand.active_filter(),
    )
    if device_id is not None:
        query = query.where(DeviceCommand.device_id == device_id)
    commands = db.session.scalars(query).all()
    now = utcnow()
    for command in commands:
        command.status = "failed"
        command.failed_at = now
        command.error = "State confirmation timeout"
    return len(commands)


def release_sent_commands_matching_state(*, device_id: UUID | None = None) -> int:
    """Unlock the queue once the board has already reported the requested outputs."""
    query = (
        db.select(DeviceCommand, Device)
        .join(Device, Device.id == DeviceCommand.device_id)
        .where(
            DeviceCommand.status == "sent",
            DeviceCommand.active_filter(),
            Device.active_filter(),
            Device.protocol_version == "2",
        )
    )
    if device_id is not None:
        query = query.where(DeviceCommand.device_id == device_id)
    now = utcnow()
    released = 0
    for command, device in db.session.execute(query):
        if not payload_matches_actual(command.payload, device.actual_state):
            continue
        command.status = "completed"
        command.acknowledged_at = command.acknowledged_at or now
        command.state_confirmed_at = now
        command.error = None
        released += 1
    return released


def expire_sent_command_timeouts(*, device_id: UUID | None = None) -> int:
    """Fail sent commands whose ACK never arrived, so the buttons do not stay dead."""
    timeout = int(current_app.config["DEVICE_COMMAND_TIMEOUT_SECONDS"])
    deadline = utcnow() - timedelta(seconds=timeout)
    query = db.select(DeviceCommand).where(
        DeviceCommand.status == "sent",
        DeviceCommand.sent_at.is_not(None),
        DeviceCommand.sent_at < deadline,
        DeviceCommand.active_filter(),
    )
    if device_id is not None:
        query = query.where(DeviceCommand.device_id == device_id)
    commands = db.session.scalars(query).all()
    now = utcnow()
    for command in commands:
        command.status = "timeout"
        command.failed_at = now
        command.error = "ACK timeout"
    return len(commands)
