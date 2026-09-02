"""Модели дефектов."""

from app.models.defects.defect import Defect
from app.models.defects.defect_category import DefectCategory
from app.models.defects.defect_history import DefectHistory
from app.models.defects.defect_status import DefectStatus

__all__ = [
    "Defect",
    "DefectCategory",
    "DefectHistory",
    "DefectStatus",
]
