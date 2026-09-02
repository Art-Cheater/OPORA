"""План работ мастера."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.work_plans.work_plan_history import WorkPlanHistory
    from app.models.work_plans.work_plan_item import WorkPlanItem


class WorkPlan(BaseModel):
    """План работ: сразу «в работе» после сохранения, затем завершается автоматически."""

    __tablename__ = "work_plans"
    __table_args__ = (
        Index("ix_work_plans_number", "number", unique=True),
        Index("ix_work_plans_master_id", "master_id"),
        Index("ix_work_plans_status", "status"),
        Index("ix_work_plans_deleted_created", "deleted_at", "created_at"),
        Index(
            "uq_work_plans_master_draft",
            "master_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status = 'draft'"),
            sqlite_where=text("deleted_at IS NULL AND status = 'draft'"),
        ),
    )

    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    master_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    master: Mapped[User] = relationship(
        "User",
        foreign_keys=[master_id],
    )
    items: Mapped[list[WorkPlanItem]] = relationship(
        "WorkPlanItem",
        back_populates="plan",
        foreign_keys="WorkPlanItem.plan_id",
        lazy="select",
        order_by="WorkPlanItem.sort_order.asc()",
    )
    history: Mapped[list[WorkPlanHistory]] = relationship(
        "WorkPlanHistory",
        back_populates="plan",
        foreign_keys="WorkPlanHistory.plan_id",
        lazy="select",
        order_by="WorkPlanHistory.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<WorkPlan {self.number or self.id}>"
