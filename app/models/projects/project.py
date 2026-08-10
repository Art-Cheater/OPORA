"""Модель проекта."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, text
from app.models.types import GUID, SearchVectorType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ActiveRecordMixin, BaseModel
from app.models.enums import ProjectMemberRole, ProjectStatus

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.projects.project_document import ProjectDocument
    from app.models.projects.project_history import ProjectHistory
    from app.models.projects.project_member import ProjectMember
    from app.models.requests.request import Request
    from app.models.contracts.contract import Contract


class Project(ActiveRecordMixin, BaseModel):
    """Проект муниципального предприятия."""

    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "ix_projects_code_unique_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_projects_status", "status"),
        Index("ix_projects_manager_id", "manager_id"),
        Index("ix_projects_start_date", "start_date"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default=ProjectStatus.DRAFT.value,
        nullable=False,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_vector: Mapped[str | None] = mapped_column(SearchVectorType, nullable=True)

    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    manager: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[manager_id],
    )
    members: Mapped[list[ProjectMember]] = relationship(
        "ProjectMember",
        back_populates="project",
        lazy="selectin",
    )
    requests: Mapped[list[Request]] = relationship(
        "Request",
        back_populates="project",
        lazy="selectin",
    )
    contracts: Mapped[list[Contract]] = relationship(
        "Contract",
        back_populates="project",
        lazy="selectin",
    )
    history: Mapped[list[ProjectHistory]] = relationship(
        "ProjectHistory",
        back_populates="project",
        foreign_keys="ProjectHistory.project_id",
        lazy="selectin",
        order_by="ProjectHistory.created_at.desc()",
    )
    documents: Mapped[list[ProjectDocument]] = relationship(
        "ProjectDocument",
        back_populates="project",
        foreign_keys="ProjectDocument.project_id",
        lazy="selectin",
        order_by="ProjectDocument.created_at.desc()",
    )

    @property
    def responsible(self) -> User | None:
        return self.manager

    @property
    def responsible_id(self) -> uuid.UUID | None:
        return self.manager_id

    @property
    def active_members(self) -> list[ProjectMember]:
        return [member for member in self.members if member.deleted_at is None]

    @property
    def executors(self) -> list[User]:
        return [
            member.user
            for member in self.active_members
            if member.role_in_project == ProjectMemberRole.EXECUTOR.value and member.user is not None
        ]

    def __repr__(self) -> str:
        return f"<Project {self.code}>"
