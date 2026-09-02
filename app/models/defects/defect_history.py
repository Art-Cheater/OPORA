"""История изменений дефекта."""

from __future__ import annotations

import uuid
from typing import Any
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from app.models.types import GUID, JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.defects.defect import Defect
    from app.models.defects.defect_status import DefectStatus


class DefectHistory(BaseModel):
    """История изменений дефекта."""

    __tablename__ = "defect_history"
    __table_args__ = (
        Index("ix_defect_history_defect_id", "defect_id"),
        Index("ix_defect_history_status_id", "status_id"),
        Index("ix_defect_history_changed_by", "changed_by"),
    )

    defect_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("defects.id", ondelete="CASCADE"),
        nullable=False,
    )
    status_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("defect_statuses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_status_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("defect_statuses.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="update")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    defect: Mapped[Defect] = relationship(
        "Defect",
        back_populates="history",
        foreign_keys=[defect_id],
    )
    status: Mapped[DefectStatus] = relationship(
        "DefectStatus",
        back_populates="history_entries",
        foreign_keys=[status_id],
    )
    previous_status: Mapped[DefectStatus | None] = relationship(
        "DefectStatus",
        foreign_keys=[previous_status_id],
    )
    changed_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[changed_by],
    )
