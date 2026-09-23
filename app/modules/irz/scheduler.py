"""Lightweight staggered polling worker for live ATM21 sessions."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models.irz import IRZDevice
from app.modules.irz import service


def schedule_offsets(imeis: list[str], interval: int = 600) -> dict[str, int]:
    ordered = sorted(set(imeis))
    count = len(ordered)
    return {imei: (index * interval) // count for index, imei in enumerate(ordered)} if count else {}


def due_devices(now: datetime | None = None) -> list[IRZDevice]:
    now = now or datetime.now(timezone.utc)
    interval = max(60, int(current_app.config.get("IRZ_AUTO_POLL_INTERVAL_SECONDS", 600)))
    devices = list(db.session.scalars(db.select(IRZDevice).where(
        IRZDevice.active_filter(), IRZDevice.enabled.is_(True), IRZDevice.imei.is_not(None)
    ).order_by(IRZDevice.imei)))
    offsets = schedule_offsets([item.imei for item in devices], interval)
    second = int(now.timestamp()) % interval
    return [item for item in devices if offsets[item.imei] == second and
            (item.last_polled_at is None or now - service._aware(item.last_polled_at) >= timedelta(seconds=interval - 1))]


def run_once(now: datetime | None = None) -> dict[str, int]:
    result = {"polled": 0, "failed": 0, "busy": 0}
    try:
        online = {item.get("imei") for item in service.get_devices()}
    except (service.GatewayUnavailable, service.GatewayResponseError):
        return result
    for device in due_devices(now):
        if device.imei not in online:
            continue
        try:
            service.poll_device(device, user_id=None, source="AUTO", log_operations=False)
            result["polled"] += 1
        except ValueError as exc:
            result["busy" if str(exc) == "POLL_IN_PROGRESS" else "failed"] += 1
        except (service.GatewayUnavailable, service.GatewayResponseError) as exc:
            device.last_error_at = datetime.now(timezone.utc)
            device.last_error = str(exc)
            db.session.commit()
            result["failed"] += 1
    return result


def run_loop() -> None:
    while True:
        run_once()
        time.sleep(1)
