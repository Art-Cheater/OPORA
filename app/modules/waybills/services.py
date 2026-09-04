"""Сервис путевых листов."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.audit_service import AuditService
from app.core.exceptions import ValidationError
from app.core.nearby import NearbySearchService
from app.extensions import db
from app.models.defects.defect import Defect
from app.models.enums import AuditAction, EntityType
from app.models.requests.request import Request
from app.models.waybills.waybill import Waybill
from app.models.waybills.waybill_history import WaybillHistory
from app.models.waybills.waybill_member import WaybillMember
from app.models.waybills.waybill_stop import WaybillStop
from app.modules.waybills.workflow import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_DRAFT, STATUS_IN_PROGRESS, can_transition


@dataclass
class WaybillPayload:
    number: str
    work_date: date
    master_id: uuid.UUID
    comment: str | None
    member_ids: list[uuid.UUID]


class WaybillService:
    @classmethod
    def _log_audit(cls, user_id, action, entity_id, description, old_values=None, new_values=None):
        AuditService.log(
            user_id=user_id,
            action=action,
            entity_type=EntityType.WAYBILL.value,
            entity_id=entity_id,
            description=description,
            old_values=old_values,
            new_values=new_values,
        )

    @staticmethod
    def _log_history(waybill: Waybill, user_id, action: str, comment: str | None = None, details=None):
        db.session.add(
            WaybillHistory(
                waybill_id=waybill.id,
                action=action,
                comment=comment,
                details=details,
                changed_by=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    @classmethod
    def create(cls, payload: WaybillPayload, user_id: uuid.UUID) -> Waybill:
        if not payload.number.strip():
            raise ValidationError("Номер обязателен.")
        if payload.master_id is None:
            raise ValidationError("Укажите мастера.")
        exists = db.session.scalar(db.select(Waybill.id).where(Waybill.number == payload.number.strip()).limit(1))
        if exists:
            raise ValidationError("Путевой лист с таким номером уже существует.")
        item = Waybill(
            number=payload.number.strip(),
            work_date=payload.work_date,
            master_id=payload.master_id,
            comment=(payload.comment or "").strip() or None,
            status=STATUS_DRAFT,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(item)
        try:
            db.session.flush()
        except IntegrityError as exc:
            db.session.rollback()
            raise ValidationError("Путевой лист с таким номером уже существует.") from exc
        cls._sync_members(item, payload.member_ids, user_id)
        cls._log_audit(user_id, AuditAction.CREATE.value, item.id, f"Создан путевой лист {item.number}")
        cls._log_history(item, user_id, "create", "Создан путевой лист")
        db.session.commit()
        return item

    @classmethod
    def update(cls, item: Waybill, payload: WaybillPayload, user_id: uuid.UUID) -> Waybill:
        item.number = payload.number.strip()
        item.work_date = payload.work_date
        item.master_id = payload.master_id
        item.comment = (payload.comment or "").strip() or None
        item.updated_by = user_id
        cls._sync_members(item, payload.member_ids, user_id)
        cls._log_audit(user_id, AuditAction.UPDATE.value, item.id, f"Изменён путевой лист {item.number}")
        cls._log_history(item, user_id, "update")
        db.session.commit()
        return item

    @staticmethod
    def _sync_members(item: Waybill, member_ids: list[uuid.UUID], user_id: uuid.UUID) -> None:
        wanted = {mid for mid in member_ids if mid}
        existing = list(
            db.session.scalars(db.select(WaybillMember).where(WaybillMember.waybill_id == item.id))
        )
        by_user = {m.user_id: m for m in existing}
        for uid, row in by_user.items():
            if uid not in wanted and row.deleted_at is None:
                row.soft_delete(deleted_by=user_id)
        for uid in wanted:
            row = by_user.get(uid)
            if row is None:
                db.session.add(
                    WaybillMember(waybill_id=item.id, user_id=uid, created_by=user_id, updated_by=user_id)
                )
            elif row.deleted_at is not None:
                row.deleted_at = None
                row.updated_by = user_id

    @staticmethod
    def _ensure_open(item: Waybill) -> None:
        if item.status in {STATUS_COMPLETED, STATUS_CANCELLED}:
            raise ValidationError("Путевой лист уже закрыт. Изменить план нельзя.")

    @classmethod
    def change_status(cls, item: Waybill, status: str, user_id: uuid.UUID) -> Waybill:
        if not can_transition(item.status, status):
            raise ValidationError("Недопустимый переход статуса.")
        old = item.status
        item.status = status
        item.updated_by = user_id
        if status == STATUS_COMPLETED:
            cls._mark_plan_defects_fixed(item, user_id)
        cls._log_audit(user_id, AuditAction.STATUS_CHANGE.value, item.id, f"Статус {item.number}: {old} → {status}")
        cls._log_history(item, user_id, "status_change", details={"from": old, "to": status})
        db.session.commit()
        return item

    @classmethod
    def complete(cls, item: Waybill, user_id: uuid.UUID) -> Waybill:
        if item.status == STATUS_DRAFT:
            item = cls.change_status(item, STATUS_IN_PROGRESS, user_id)
        if item.status != STATUS_IN_PROGRESS:
            raise ValidationError("Путевой лист нельзя завершить.")
        return cls.change_status(item, STATUS_COMPLETED, user_id)

    @classmethod
    def _mark_plan_defects_fixed(cls, waybill: Waybill, user_id: uuid.UUID) -> None:
        from sqlalchemy.orm import joinedload

        from app.modules.defects.services import DefectService

        stops = db.session.scalars(
            db.select(WaybillStop)
            .options(joinedload(WaybillStop.defect).joinedload(Defect.status))
            .where(
                WaybillStop.waybill_id == waybill.id,
                WaybillStop.active_filter(),
                WaybillStop.defect_id.isnot(None),
            )
        ).unique()
        for stop in stops:
            if stop.defect is None or stop.defect.deleted_at is not None:
                continue
            DefectService.mark_fixed_in_session(
                stop.defect,
                user_id,
                comment=f"Закрыт по завершению путевого листа {waybill.number}",
            )

    @classmethod
    def delete(cls, item: Waybill, user_id: uuid.UUID) -> None:
        item.soft_delete(deleted_by=user_id)
        cls._log_audit(user_id, AuditAction.SOFT_DELETE.value, item.id, f"Удалён путевой лист {item.number}")
        db.session.commit()

    @classmethod
    def add_stop(cls, item: Waybill, *, entity_type: str, entity_id: uuid.UUID, user_id: uuid.UUID, comment: str | None = None) -> WaybillStop:
        cls._ensure_open(item)
        if entity_type == "request":
            target = db.session.scalar(db.select(Request).where(Request.id == entity_id, Request.active_filter()))
            if target is None:
                raise ValidationError("Заявка не найдена.")
            if cls.entity_in_other_active_work(request_id=target.id, skip_waybill_id=item.id):
                raise ValidationError("Эта заявка уже входит в другой активный план.")
            already = db.session.scalar(
                db.select(WaybillStop.id).where(
                    WaybillStop.waybill_id == item.id,
                    WaybillStop.request_id == target.id,
                    WaybillStop.active_filter(),
                )
            )
            if already:
                raise ValidationError("Эта заявка уже в путевом листе.")
            stop = WaybillStop(
                waybill_id=item.id,
                sort_order=cls._next_order(item.id),
                request_id=target.id,
                address=target.address,
                latitude=target.latitude,
                longitude=target.longitude,
                comment=comment,
                created_by=user_id,
                updated_by=user_id,
            )
        elif entity_type == "defect":
            target = db.session.scalar(db.select(Defect).where(Defect.id == entity_id, Defect.active_filter()))
            if target is None:
                raise ValidationError("Дефект не найден.")
            if cls.entity_in_other_active_work(defect_id=target.id, skip_waybill_id=item.id):
                raise ValidationError("Этот дефект уже входит в другой активный план.")
            already = db.session.scalar(
                db.select(WaybillStop.id).where(
                    WaybillStop.waybill_id == item.id,
                    WaybillStop.defect_id == target.id,
                    WaybillStop.active_filter(),
                )
            )
            if already:
                raise ValidationError("Этот дефект уже в путевом листе.")
            stop = WaybillStop(
                waybill_id=item.id,
                sort_order=cls._next_order(item.id),
                defect_id=target.id,
                address=target.address,
                latitude=target.latitude,
                longitude=target.longitude,
                comment=comment,
                created_by=user_id,
                updated_by=user_id,
            )
        else:
            raise ValidationError("Неизвестный тип точки.")
        db.session.add(stop)
        db.session.flush()
        cls._apply_add_status(stop, target, entity_type, user_id)
        cls._log_audit(user_id, AuditAction.UPDATE.value, item.id, f"Добавлена точка в {item.number}", new_values={"stop": stop.address})
        cls._log_history(item, user_id, "add_stop", stop.address, {"entity_type": entity_type, "entity_id": str(entity_id)})
        db.session.commit()
        return stop

    @classmethod
    def _apply_add_status(cls, stop: WaybillStop, target, entity_type: str, user_id: uuid.UUID) -> None:
        from app.modules.defects.services import DefectService
        from app.modules.defects.workflow import STATUS_IN_PROGRESS as DEFECT_IN_PROGRESS
        from app.modules.requests.services import RequestService
        from app.modules.requests.workflow import STATUS_IN_PROGRESS as REQ_IN_PROGRESS

        if entity_type == "request":
            previous = target.status.code if target.status else ""
            if previous and previous != REQ_IN_PROGRESS:
                RequestService.mark_in_progress_in_session(target.id, user_id)
                stop.previous_status_code = previous
        elif entity_type == "defect":
            previous = target.status.code if target.status else ""
            if previous and previous != DEFECT_IN_PROGRESS:
                DefectService.mark_in_progress_in_session(target, user_id)
                stop.previous_status_code = previous

    @staticmethod
    def entity_in_other_active_work(
        *,
        request_id: uuid.UUID | None = None,
        defect_id: uuid.UUID | None = None,
        skip_waybill_id: uuid.UUID | None = None,
        skip_plan_id: uuid.UUID | None = None,
    ) -> bool:
        from app.models.work_plans.work_plan import WorkPlan
        from app.models.work_plans.work_plan_item import WorkPlanItem
        from app.modules.work_orders.plan_service import ITEM_ACTIVE, PLAN_DRAFT, PLAN_IN_PROGRESS

        stop_stmt = (
            db.select(WaybillStop.id)
            .join(Waybill, Waybill.id == WaybillStop.waybill_id)
            .where(
                WaybillStop.active_filter(),
                Waybill.active_filter(),
                Waybill.status.in_({STATUS_DRAFT, STATUS_IN_PROGRESS}),
            )
            .limit(1)
        )
        if skip_waybill_id is not None:
            stop_stmt = stop_stmt.where(WaybillStop.waybill_id != skip_waybill_id)
        if request_id is not None:
            stop_stmt = stop_stmt.where(WaybillStop.request_id == request_id)
        elif defect_id is not None:
            stop_stmt = stop_stmt.where(WaybillStop.defect_id == defect_id)
        else:
            return False
        if db.session.scalar(stop_stmt) is not None:
            return True
        item_stmt = (
            db.select(WorkPlanItem.id)
            .join(WorkPlan, WorkPlan.id == WorkPlanItem.plan_id)
            .where(
                WorkPlanItem.active_filter(),
                WorkPlan.active_filter(),
                WorkPlan.status.in_({PLAN_DRAFT, PLAN_IN_PROGRESS}),
                WorkPlanItem.result == ITEM_ACTIVE,
            )
            .limit(1)
        )
        if skip_plan_id is not None:
            item_stmt = item_stmt.where(WorkPlanItem.plan_id != skip_plan_id)
        if request_id is not None:
            item_stmt = item_stmt.where(WorkPlanItem.request_id == request_id)
        else:
            item_stmt = item_stmt.where(WorkPlanItem.defect_id == defect_id)
        return db.session.scalar(item_stmt) is not None

    @staticmethod
    def _next_order(waybill_id: uuid.UUID) -> int:
        current = db.session.scalar(
            db.select(db.func.max(WaybillStop.sort_order)).where(
                WaybillStop.waybill_id == waybill_id,
                WaybillStop.active_filter(),
            )
        ) or 0
        return int(current) + 1

    @classmethod
    def remove_stop(cls, item: Waybill, stop_id: uuid.UUID, user_id: uuid.UUID) -> None:
        cls._ensure_open(item)
        stop = db.session.scalar(
            db.select(WaybillStop).where(
                WaybillStop.id == stop_id,
                WaybillStop.waybill_id == item.id,
                WaybillStop.active_filter(),
            )
        )
        if stop is None:
            raise ValidationError("Точка не найдена.")
        cls._restore_stop_status(stop, user_id, skip_waybill_id=item.id)
        stop.soft_delete(deleted_by=user_id)
        cls._log_audit(user_id, AuditAction.UPDATE.value, item.id, f"Удалена точка из {item.number}", old_values={"stop": stop.address})
        cls._log_history(item, user_id, "remove_stop", stop.address)
        db.session.commit()

    @classmethod
    def _restore_stop_status(cls, stop: WaybillStop, user_id: uuid.UUID, *, skip_waybill_id: uuid.UUID) -> None:
        from app.modules.defects.services import DefectService
        from app.modules.requests.services import RequestService

        if not stop.previous_status_code:
            return
        if stop.request_id and cls.entity_in_other_active_work(
            request_id=stop.request_id, skip_waybill_id=skip_waybill_id
        ):
            return
        if stop.defect_id and cls.entity_in_other_active_work(
            defect_id=stop.defect_id, skip_waybill_id=skip_waybill_id
        ):
            return
        if stop.request_id:
            RequestService.restore_from_plan_in_session(stop.request_id, user_id, stop.previous_status_code)
        elif stop.defect_id:
            defect = stop.defect or db.session.get(Defect, stop.defect_id)
            if defect is not None:
                DefectService.restore_from_plan_in_session(defect, user_id, stop.previous_status_code)

    @classmethod
    def reorder_stops(cls, item: Waybill, stop_ids: list[uuid.UUID], user_id: uuid.UUID) -> None:
        cls._ensure_open(item)
        stops = {
            s.id: s
            for s in db.session.scalars(
                db.select(WaybillStop).where(WaybillStop.waybill_id == item.id, WaybillStop.active_filter())
            )
        }
        if set(stop_ids) != set(stops):
            raise ValidationError("Список точек не совпадает.")
        # Двухфазный сдвиг, чтобы не нарушать unique (waybill_id, sort_order)
        for offset, stop_id in enumerate(stop_ids, start=1):
            stops[stop_id].sort_order = 1000 + offset
        db.session.flush()
        for order, stop_id in enumerate(stop_ids, start=1):
            stops[stop_id].sort_order = order
            stops[stop_id].updated_by = user_id
        cls._log_audit(user_id, AuditAction.UPDATE.value, item.id, f"Изменён порядок точек {item.number}")
        cls._log_history(item, user_id, "reorder", details={"stop_ids": [str(i) for i in stop_ids]})
        db.session.commit()

    @classmethod
    def nearby_for_stop(cls, item: Waybill, stop: WaybillStop):
        exclude_req = [s.request_id for s in item.stops if s.request_id and s.deleted_at is None]
        exclude_def = [s.defect_id for s in item.stops if s.defect_id and s.deleted_at is None]
        hits = NearbySearchService.suggest(
            address=stop.address,
            street=(stop.request.street if stop.request else (stop.defect.street if stop.defect else None)),
            district=(stop.request.district if stop.request else (stop.defect.district if stop.defect else None)),
            latitude=stop.latitude,
            longitude=stop.longitude,
            exclude_request_ids=exclude_req,
            exclude_defect_ids=exclude_def,
        )
        return hits, NearbySearchService.summarize(hits)
