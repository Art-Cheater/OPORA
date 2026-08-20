"""Планировщик забора писем с корпоративного ящика."""

from __future__ import annotations

import logging
import time

from flask import current_app

from app.extensions import db
from app.modules.inquiries.services import InquiryService

logger = logging.getLogger(__name__)


def run_once() -> None:
    result = InquiryService.sync()
    if result.error:
        logger.warning("Обращения: %s", result.error)
        return
    logger.info("Обращения: новых %s, пропущено %s", result.fetched, result.skipped)


def run_loop() -> None:
    interval = int(current_app.config.get("INQUIRY_SYNC_INTERVAL_SECONDS") or 120)
    logger.info("Планировщик обращений каждые %s с", interval)
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Сбой забора писем")
            db.session.rollback()
        time.sleep(max(30, interval))
