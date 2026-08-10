"""Общие миксины для моделей (legacy, используйте app.models.base)."""

from app.models.base import ActiveRecordMixin, BaseModel, utcnow

__all__ = ["BaseModel", "ActiveRecordMixin", "utcnow"]
