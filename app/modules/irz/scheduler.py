"""Staggered server-side polling of live ATM21 sessions.

Every device gets a fixed offset inside the interval (600 IRZ → one start per second).
Devices are polled in parallel; the modem gateway serializes transactions per ATM21.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from flask import current_app

from app.extensions import db
from app.models.irz import IRZDevice
from app.modules.irz import service

logger = logging.getLogger(__name__)


def schedule_offsets(imeis: list[str], interval: int = 600) -> dict[str, int]:
    ordered = sorted(set(imeis))
    count = len(ordered)
    return {imei: (index * interval) // count for index, imei in enumerate(ordered)} if count else {}


def slot_start(timestamp: int, offset: int, interval: int) -> int:
    """Start of the most recent slot of a device with the given offset (not later than timestamp)."""
    slot = timestamp - timestamp % interval + offset
    return slot - interval if slot > timestamp else slot


def _interval() -> int:
    return max(60, int(current_app.config.get("IRZ_AUTO_POLL_INTERVAL_SECONDS", 600)))


def due_devices(now: datetime | None = None, online: set[str] | None = None) -> list[IRZDevice]:
    now = now or datetime.now(timezone.utc)
    interval = _interval()
    devices = list(db.session.scalars(db.select(IRZDevice).where(
        IRZDevice.active_filter(), IRZDevice.enabled.is_(True), IRZDevice.imei.is_not(None)
    ).order_by(IRZDevice.imei)))
    offsets = schedule_offsets([item.imei for item in devices], interval)
    timestamp = int(now.timestamp())
    due = []
    for item in devices:
        if online is not None and item.imei not in online:
            continue
        slot = datetime.fromtimestamp(slot_start(timestamp, offsets[item.imei], interval), timezone.utc)
        if item.last_polled_at is None or service._aware(item.last_polled_at) < slot:
            due.append(item)
    return due


def poll_one(device_id) -> str:
    device = db.session.get(IRZDevice, device_id)
    if device is None or not device.enabled:
        return "skipped"
    try:
        service.poll_device(device, user_id=None, source="AUTO", log_operations=False)
        return "polled"
    except ValueError as exc:
        db.session.rollback()
        return "busy" if str(exc) == "POLL_IN_PROGRESS" else "failed"
    except (service.GatewayUnavailable, service.GatewayResponseError):
        return "failed"


def run_once(now: datetime | None = None) -> dict[str, int]:
    """Synchronous single pass (CLI and tests)."""
    result = {"polled": 0, "failed": 0, "busy": 0, "skipped": 0}
    try:
        online = {item.get("imei") for item in service.get_devices()}
    except (service.GatewayUnavailable, service.GatewayResponseError):
        return result
    for device_id in [item.id for item in due_devices(now, online)]:
        result[poll_one(device_id)] += 1
    return result


def run_loop() -> None:
    app = current_app._get_current_object()
    workers = max(1, int(app.config.get("IRZ_POLL_WORKERS", 8)))
    in_flight: set = set()
    lock = threading.Lock()

    def worker(device_id) -> None:
        try:
            with app.app_context():
                try:
                    poll_one(device_id)
                except Exception:
                    logger.exception("IRZ auto poll failed")
                finally:
                    db.session.remove()
        finally:
            with lock:
                in_flight.discard(device_id)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="irz-poll") as executor:
        while True:
            try:
                online = {item.get("imei") for item in service.get_devices()}
                due = [item.id for item in due_devices(online=online)]
            except (service.GatewayUnavailable, service.GatewayResponseError):
                due = []
            except Exception:
                logger.exception("IRZ scheduler tick failed")
                due = []
            finally:
                db.session.remove()
            for device_id in due:
                with lock:
                    if device_id in in_flight or len(in_flight) >= workers * 4:
                        continue
                    in_flight.add(device_id)
                executor.submit(worker, device_id)
            time.sleep(1)
