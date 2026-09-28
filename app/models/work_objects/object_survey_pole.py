"""Точка обследования объекта: опора на карте лота, не городской мониторинг."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.enums import SurveyPoleKind, SurveyPoleType
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.work_objects.work_object import WorkObject


class ObjectSurveyPole(BaseModel):
    """Опора обследования адресного объекта. В IRZ/light_poles не пишется."""

    __tablename__ = "object_survey_poles"
    __table_args__ = (
        Index("ix_object_survey_poles_object", "object_id"),
        Index("ix_object_survey_poles_lat_lng", "latitude", "longitude"),
        Index("ix_object_survey_poles_deleted_created", "deleted_at", "created_at"),
        CheckConstraint(
            "kind IN ('existing', 'planned')",
            name="ck_object_survey_poles_kind",
        ),
        CheckConstraint(
            "pole_type IN ('concrete', 'metal', 'other')",
            name="ck_object_survey_poles_type",
        ),
        CheckConstraint(
            "source IN ('gps', 'manual')",
            name="ck_object_survey_poles_source",
        ),
    )

    object_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("work_objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(20),
        default=SurveyPoleKind.EXISTING.value,
        nullable=False,
    )
    pole_type: Mapped[str] = mapped_column(
        String(20),
        default=SurveyPoleType.METAL.value,
        nullable=False,
    )
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    work_object: Mapped[WorkObject] = relationship(
        "WorkObject",
        foreign_keys=[object_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<ObjectSurveyPole {self.kind} {self.pole_type} {self.sequence}>"
