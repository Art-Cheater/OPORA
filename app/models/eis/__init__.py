"""Модели журнала импорта ЕИС."""

from app.models.eis.eis_import_event import EisImportEvent
from app.models.eis.eis_import_run import EisImportRun

__all__ = ["EisImportRun", "EisImportEvent"]
