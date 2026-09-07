"""Дополнительные точки сложного адреса Request/Defect."""
from __future__ import annotations
import uuid
from decimal import Decimal
from sqlalchemy import Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import BaseModel
from app.models.types import GUID


class WorkMapPoint(BaseModel):
    __tablename__ = "work_map_points"
    __table_args__ = (
        Index("ix_work_map_points_entity", "entity_type", "entity_id"),
        Index("ix_work_map_points_lat_lng", "latitude", "longitude"),
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    address_part: Mapped[str] = mapped_column(String(1000), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    confidence: Mapped[str] = mapped_column(String(30), nullable=False, default="approximate")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)
