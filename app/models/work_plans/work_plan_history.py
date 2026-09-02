"""История действий по плану работ."""

from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.types import GUID, JSONType

if TYPE_CHECKING:
    from app.models.auth.user import User
    from app.models.work_plans.work_plan import WorkPlan
    from app.models.work_plans.work_plan_item import WorkPlanItem


class WorkPlanHistory(BaseModel):
    """Событие плана: создание, сохранение, выполнение, исключение, завершение."""

    __tablename__ = "work_plan_history"
    __table_args__ = (
        Index("ix_work_plan_history_plan_id", "plan_id"),
        Index("ix_work_plan_history_item_id", "item_id"),
        Index("ix_work_plan_history_changed_by", "changed_by"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("work_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("work_plan_items.id", ondelete="SET NULL"),
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

    plan: Mapped[WorkPlan] = relationship(
        "WorkPlan",
        back_populates="history",
        foreign_keys=[plan_id],
    )
    item: Mapped[WorkPlanItem | None] = relationship(
        "WorkPlanItem",
        foreign_keys=[item_id],
    )
    changed_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[changed_by],
    )
