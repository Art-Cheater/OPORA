"""Участники проекта."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from app.models.types import GUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel, utcnow
from app.models.enums import ProjectMemberRole

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.projects.project import Project


class ProjectMember(BaseModel):
    """Участник проекта (Many-to-Many с дополнительными полями)."""

    __tablename__ = "project_members"
    __table_args__ = (
        Index("ix_project_members_project_id", "project_id"),
        Index("ix_project_members_user_id", "user_id"),
        Index(
            "ix_project_members_unique_active",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_in_project: Mapped[str] = mapped_column(
        String(30),
        default=ProjectMemberRole.MEMBER.value,
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="members",
        foreign_keys=[project_id],
    )
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
    )

    def __repr__(self) -> str:
        return f"<ProjectMember project={self.project_id} user={self.user_id}>"
