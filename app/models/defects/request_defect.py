"""Связь заявка ↔ дефект."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.defects.defect import Defect
    from app.models.requests.request import Request


class RequestDefect(BaseModel):
    """Реляционная связь заявки и дефекта."""

    __tablename__ = "request_defects"
    __table_args__ = (
        Index(
            "uq_request_defects_pair",
            "request_id",
            "defect_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_request_defects_request_id", "request_id"),
        Index("ix_request_defects_defect_id", "defect_id"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    defect_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("defects.id", ondelete="CASCADE"),
        nullable=False,
    )

    request: Mapped[Request] = relationship(
        "Request",
        back_populates="defect_links",
        foreign_keys=[request_id],
    )
    defect: Mapped[Defect] = relationship(
        "Defect",
        back_populates="request_links",
        foreign_keys=[defect_id],
    )
