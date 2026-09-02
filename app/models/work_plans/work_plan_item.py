"""Элемент плана работ: заявка XOR дефект."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.defects.defect import Defect
    from app.models.requests.request import Request
    from app.models.work_plans.work_plan import WorkPlan


class WorkPlanItem(BaseModel):
    """Одна работа в плане. Не дублирует заявку или дефект."""

    __tablename__ = "work_plan_items"
    __table_args__ = (
        CheckConstraint(
            "(request_id IS NOT NULL AND defect_id IS NULL) "
            "OR (request_id IS NULL AND defect_id IS NOT NULL)",
            name="ck_work_plan_items_one_target",
        ),
        Index("ix_work_plan_items_plan_id", "plan_id"),
        Index("ix_work_plan_items_request_id", "request_id"),
        Index("ix_work_plan_items_defect_id", "defect_id"),
        Index("ix_work_plan_items_result", "result"),
        Index(
            "uq_work_plan_items_request",
            "plan_id",
            "request_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND request_id IS NOT NULL"),
            sqlite_where=text("deleted_at IS NULL AND request_id IS NOT NULL"),
        ),
        Index(
            "uq_work_plan_items_defect",
            "plan_id",
            "defect_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND defect_id IS NOT NULL"),
            sqlite_where=text("deleted_at IS NULL AND defect_id IS NOT NULL"),
        ),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("work_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("requests.id", ondelete="RESTRICT"),
        nullable=True,
    )
    defect_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("defects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    result: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    number_snapshot: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    address_snapshot: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    pp_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    street_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    district_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previous_status_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    complete_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    exclude_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exclude_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    excluded_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    plan: Mapped[WorkPlan] = relationship(
        "WorkPlan",
        back_populates="items",
        foreign_keys=[plan_id],
    )
    request: Mapped[Request | None] = relationship(
        "Request",
        foreign_keys=[request_id],
    )
    defect: Mapped[Defect | None] = relationship(
        "Defect",
        foreign_keys=[defect_id],
    )
    completed_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[completed_by],
    )
    excluded_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[excluded_by],
    )

    @property
    def entity_type(self) -> str:
        return "request" if self.request_id else "defect"

    def __repr__(self) -> str:
        return f"<WorkPlanItem {self.number_snapshot} {self.result}>"
