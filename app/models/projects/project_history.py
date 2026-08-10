"""История изменений проекта."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, Text
from app.models.types import GUID, JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.projects.project import Project


class ProjectHistory(BaseModel):
    """История изменений проекта."""

    __tablename__ = "project_history"
    __table_args__ = (
        Index("ix_project_history_project_id", "project_id"),
        Index("ix_project_history_changed_by", "changed_by"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="update")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="history",
        foreign_keys=[project_id],
    )
    changed_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[changed_by],
    )

    def __repr__(self) -> str:
        return f"<ProjectHistory project={self.project_id} action={self.action}>"
