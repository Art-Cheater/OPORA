"""Расписание прогонов ЕИС: 12:00 и 18:00 Europe/Moscow по умолчанию."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import current_app

from app.extensions import db
from app.models.auth.user import User
from app.modules.eis.services import EisImportService, EisSyncLocked

logger = logging.getLogger(__name__)


def audit_user_id(email: str | None = None) -> uuid.UUID | None:
    stmt = db.select(User).where(User.active_filter())
    if email:
        user = db.session.scalar(stmt.where(User.email == email.lower().strip()))
        if user is not None:
            return user.id
    return db.session.scalar(
        db.select(User.id).where(User.active_filter()).order_by(User.created_at.asc()).limit(1)
    )


def sync_hours() -> list[int]:
    raw = str(current_app.config.get("EIS_SYNC_HOURS") or "12,18")
    hours: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            continue
        if 0 <= value <= 23:
            hours.append(value)
    return hours or [12, 18]


def next_run_at(now: datetime | None = None) -> datetime:
    tz = ZoneInfo(current_app.config.get("EIS_SYNC_TIMEZONE") or "Europe/Moscow")
    current = (now or datetime.now(tz)).astimezone(tz)
    hours = sorted(sync_hours())
    for hour in hours:
        candidate = current.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > current + timedelta(seconds=5):
            return candidate
    tomorrow = current.replace(hour=hours[0], minute=0, second=0, microsecond=0) + timedelta(days=1)
    return tomorrow


def run_once(*, trigger: str = "schedule", user_email: str | None = None) -> None:
    user_id = audit_user_id(user_email)
    EisImportService().sync(trigger=trigger, user_id=user_id)


def run_loop() -> None:
    logger.info("Планировщик ЕИС запущен, часы: %s", sync_hours())
    while True:
        target = next_run_at()
        delay = max(5.0, (target - datetime.now(target.tzinfo)).total_seconds())
        logger.info("Следующий прогон ЕИС: %s (через %.0f с)", target.isoformat(), delay)
        time.sleep(min(delay, 3600))
        if datetime.now(target.tzinfo) < target:
            continue
        try:
            run_once(trigger="schedule")
        except EisSyncLocked:
            logger.warning("Прогон ЕИС пропущен: уже выполняется")
        except Exception:
            logger.exception("Прогон ЕИС завершился с ошибкой")
            db.session.rollback()
        finally:
            db.session.remove()
        time.sleep(60)
