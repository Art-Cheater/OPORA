"""Планировщик напоминаний о сроках личных договоров."""

from __future__ import annotations

import logging
import time

from flask import current_app

from app.extensions import db
from app.modules.documents.services import PersonalContractService

logger = logging.getLogger(__name__)


def run_once() -> dict[str, int]:
    result = PersonalContractService.send_due_reminders()
    logger.info(
        "Договоры: напоминаний за месяц=%s, за 2 недели=%s",
        result.get("month", 0),
        result.get("two_weeks", 0),
    )
    return result


def run_loop() -> None:
    # Раз в 6 часов достаточно: окна «месяц» и «2 недели» широкие.
    interval = int(current_app.config.get("DOCUMENTS_NOTIFY_INTERVAL_SECONDS") or 21600)
    logger.info("Планировщик напоминаний по договорам каждые %s с", interval)
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Сбой напоминаний по договорам")
            db.session.rollback()
        finally:
            db.session.remove()
        time.sleep(max(3600, interval))
