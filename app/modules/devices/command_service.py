"""Small, shared lifecycle helpers for controller command confirmation."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from flask import current_app

from app.extensions import db
from app.models.base import utcnow
from app.models.devices import DeviceCommand


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
