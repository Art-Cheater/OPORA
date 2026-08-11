"""Модели заявок на торги."""

from app.models.tenders.tender_application import TenderApplication
from app.models.tenders.tender_document import TenderDocument
from app.models.tenders.tender_project import TenderProject

__all__ = ["TenderApplication", "TenderDocument", "TenderProject"]
