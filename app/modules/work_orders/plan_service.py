"""Планы работ мастера: черновик, состав, связанные работы по ПП, выполнение."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import url_for
from sqlalchemy import case, select
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.datastructures import FileStorage

from app.core.exceptions import NotFoundError, ValidationError
from app.extensions import db
from app.models.auth.user import User
from app.models.base import utcnow
from app.models.defects.defect import Defect
from app.models.defects.defect_status import DefectStatus
from app.models.enums import EntityType
from app.models.files.attachment import Attachment
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.models.work_plans.work_plan import WorkPlan
from app.models.work_plans.work_plan_history import WorkPlanHistory
from app.models.work_plans.work_plan_item import WorkPlanItem
from app.modules.defects.services import DefectService
from app.modules.defects.workflow import STATUS_FIXED as DEFECT_FIXED
from app.modules.defects.workflow import STATUS_IN_PROGRESS as DEFECT_IN_PROGRESS
from app.modules.defects.workflow import STATUS_OPEN as DEFECT_OPEN
from app.modules.requests.services import RequestService
from app.modules.requests.workflow import OPEN_STATUS_CODES

PLAN_DRAFT = "draft"
PLAN_IN_PROGRESS = "in_progress"
PLAN_COMPLETED = "completed"

ITEM_ACTIVE = "active"
ITEM_COMPLETED = "completed"
ITEM_EXCLUDED = "excluded"

ENTITY_REQUEST = "request"
ENTITY_DEFECT = "defect"

PLAN_STATUS_LABELS = {
    PLAN_DRAFT: "Черновик",
    PLAN_IN_PROGRESS: "В работе",
    PLAN_COMPLETED: "Завершён",
}
ITEM_RESULT_LABELS = {
    ITEM_ACTIVE: "В плане",
    ITEM_COMPLETED: "Выполнена",
    ITEM_EXCLUDED: "Исключена из плана",
}
EXCLUDE_REASONS = (
    ("no_access", "Нет доступа"),
    ("no_material", "Нет материала"),
    ("weather", "Погодные условия"),
    ("not_needed", "Работы не требуются"),
    ("other", "Иное"),
)
EXCLUDE_REASON_LABELS = dict(EXCLUDE_REASONS)
RELATED_LIMIT = 20


def normalize_pp(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    lowered = " ".join(raw.casefold().split())
    lowered = re.sub(r"^пп[\s.:\-]*", "", lowered)
    return lowered.strip()


class WorkPlanService:
    @staticmethod
    def _fmt_dt(value) -> str:
        if value is None:
            return ""
        try:
            return value.strftime("%d.%m.%Y %H:%M")
        except (AttributeError, TypeError, ValueError):
            return str(value)

    @staticmethod
    def _fmt_date(value) -> str:
        if value is None:
            return ""
        try:
            return value.strftime("%d.%m.%Y")
        except (AttributeError, TypeError, ValueError):
            return str(value)

    @classmethod
    def _log(
        cls,
        plan: WorkPlan,
        user_id: uuid.UUID,
        action: str,
        comment: str | None = None,
        *,
        item_id: uuid.UUID | None = None,
        details: dict | None = None,
    ) -> None:
        db.session.add(
            WorkPlanHistory(
                plan_id=plan.id,
                item_id=item_id,
                action=action,
                comment=comment,
                details=details,
                changed_by=user_id,
                created_by=user_id,
                updated_by=user_id,
            )
        )

    @classmethod
    def record_report_sent(cls, plan: WorkPlan, user: User, recipient_name: str) -> None:
        cls._log(
            plan,
            user.id,
            "report_sent",
            f"Отчёт по плану отправлен сотруднику {recipient_name}",
        )
        plan.updated_by = user.id
        db.session.commit()

    @classmethod
    def get_owned(cls, plan_id: uuid.UUID, user: User) -> WorkPlan:
        plan = db.session.scalar(
            select(WorkPlan)
            .options(
                joinedload(WorkPlan.master),
                selectinload(WorkPlan.items).joinedload(WorkPlanItem.request).joinedload(Request.status),
                selectinload(WorkPlan.items).joinedload(WorkPlanItem.request).joinedload(Request.journal),
                selectinload(WorkPlan.items).joinedload(WorkPlanItem.defect).joinedload(Defect.status),
                selectinload(WorkPlan.items).joinedload(WorkPlanItem.completed_by_user),
                selectinload(WorkPlan.items).joinedload(WorkPlanItem.excluded_by_user),
                selectinload(WorkPlan.history).joinedload(WorkPlanHistory.changed_by_user),
            )
            .where(WorkPlan.id == plan_id, WorkPlan.active_filter())
        )
        if plan is None:
            raise NotFoundError("План работ не найден.")
        if plan.master_id != user.id:
            raise ValidationError("Можно открывать только свои планы работ.")
        return plan

    @classmethod
    def current_draft(cls, user: User) -> WorkPlan | None:
        return db.session.scalar(
            select(WorkPlan)
            .where(
                WorkPlan.master_id == user.id,
                WorkPlan.status == PLAN_DRAFT,
                WorkPlan.active_filter(),
            )
            .order_by(WorkPlan.created_at.desc())
        )

    @classmethod
    def get_or_create_draft(cls, user: User) -> WorkPlan:
        draft = cls.current_draft(user)
        if draft is not None:
            return cls.get_owned(draft.id, user)
        plan = WorkPlan(
            master_id=user.id,
            status=PLAN_DRAFT,
            created_by=user.id,
            updated_by=user.id,
        )
        db.session.add(plan)
        db.session.flush()
        cls._log(plan, user.id, "create", "Создан черновик плана работ")
        db.session.commit()
        return cls.get_owned(plan.id, user)

    @classmethod
    def next_number(cls) -> str:
        year = datetime.now().year
        token = f"ПР-{year}-"
        pattern = re.compile(rf"^{re.escape(token)}(\d+)$")
        numbers = db.session.scalars(select(WorkPlan.number).where(WorkPlan.number.like(f"{token}%"))).all()
        max_seq = 0
        for raw in numbers:
            match = pattern.fullmatch((raw or "").strip())
            if match:
                max_seq = max(max_seq, int(match.group(1)))
        return f"{token}{max_seq + 1:03d}"

    @classmethod
    def _active_items(cls, plan: WorkPlan) -> list[WorkPlanItem]:
        return [item for item in plan.items if item.deleted_at is None]

    @classmethod
    def _plan_ids(cls, plan: WorkPlan) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        request_ids: set[uuid.UUID] = set()
        defect_ids: set[uuid.UUID] = set()
        for item in cls._active_items(plan):
            if item.request_id:
                request_ids.add(item.request_id)
            if item.defect_id:
                defect_ids.add(item.defect_id)
        return request_ids, defect_ids

    @classmethod
    def _busy_ids(cls, *, exclude_plan_id: uuid.UUID | None = None) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        stmt = (
            select(WorkPlanItem.request_id, WorkPlanItem.defect_id)
            .join(WorkPlan, WorkPlanItem.plan_id == WorkPlan.id)
            .where(
                WorkPlanItem.active_filter(),
                WorkPlanItem.result == ITEM_ACTIVE,
                WorkPlan.active_filter(),
                WorkPlan.status.in_((PLAN_DRAFT, PLAN_IN_PROGRESS)),
            )
        )
        if exclude_plan_id is not None:
            stmt = stmt.where(WorkPlan.id != exclude_plan_id)
        request_ids: set[uuid.UUID] = set()
        defect_ids: set[uuid.UUID] = set()
        for request_id, defect_id in db.session.execute(stmt):
            if request_id:
                request_ids.add(request_id)
            if defect_id:
                defect_ids.add(defect_id)
        return request_ids, defect_ids

    @classmethod
    def _load_entity(cls, entity_type: str, entity_id: uuid.UUID):
        if entity_type == ENTITY_REQUEST:
            item = db.session.scalar(
                select(Request)
                .options(joinedload(Request.status), joinedload(Request.journal))
                .where(Request.id == entity_id, Request.active_filter())
            )
        elif entity_type == ENTITY_DEFECT:
            item = db.session.scalar(
                select(Defect)
                .options(joinedload(Defect.status), joinedload(Defect.category))
                .where(Defect.id == entity_id, Defect.active_filter())
            )
        else:
            raise ValidationError("Укажите заявку или дефект.")
        if item is None:
            raise NotFoundError("Работа не найдена.")
        return item

    @classmethod
    def add_item(cls, plan: WorkPlan, *, entity_type: str, entity_id: uuid.UUID, user: User) -> WorkPlanItem:
        if plan.status not in {PLAN_DRAFT, PLAN_IN_PROGRESS}:
            raise ValidationError("В завершённый план нельзя добавлять работы.")
        entity = cls._load_entity(entity_type, entity_id)
        plan_requests, plan_defects = cls._plan_ids(plan)
        busy_requests, busy_defects = cls._busy_ids(exclude_plan_id=plan.id)
        if entity_type == ENTITY_REQUEST:
            if entity_id in plan_requests:
                raise ValidationError("Эта заявка уже есть в плане.")
            if entity_id in busy_requests:
                raise ValidationError("Заявка уже входит в другой активный план.")
            if entity.status and entity.status.code not in OPEN_STATUS_CODES:
                raise ValidationError("В план можно добавить только незакрытую заявку.")
        else:
            if entity_id in plan_defects:
                raise ValidationError("Этот дефект уже есть в плане.")
            if entity_id in busy_defects:
                raise ValidationError("Дефект уже входит в другой активный план.")
            code = entity.status.code if entity.status else ""
            if code not in {DEFECT_OPEN, DEFECT_IN_PROGRESS}:
                raise ValidationError("В план можно добавить только открытый дефект.")

        sort_order = max((item.sort_order for item in cls._active_items(plan)), default=0) + 1
        description = (entity.description or "") if entity_type == ENTITY_DEFECT else (entity.description or entity.title or "")
        item = WorkPlanItem(
            plan_id=plan.id,
            sort_order=sort_order,
            request_id=entity.id if entity_type == ENTITY_REQUEST else None,
            defect_id=entity.id if entity_type == ENTITY_DEFECT else None,
            result=ITEM_ACTIVE,
            number_snapshot=entity.number,
            address_snapshot=entity.address or "",
            pp_snapshot=entity.pp or "",
            description_snapshot=description,
            street_snapshot=entity.street or "",
            district_snapshot=entity.district or "",
            created_by=user.id,
            updated_by=user.id,
        )
        db.session.add(item)
        db.session.flush()
        cls._log(
            plan,
            user.id,
            "add_item",
            f"В план добавлен {entity.number}",
            item_id=item.id,
            details={"entity_type": entity_type, "entity_id": str(entity.id), "number": entity.number},
        )
        plan.updated_by = user.id
        if plan.status == PLAN_IN_PROGRESS:
            item.previous_status_code = entity.status.code if entity.status else None
            if entity_type == ENTITY_REQUEST:
                RequestService.mark_in_progress_in_session(entity.id, user.id)
            else:
                DefectService.mark_in_progress_in_session(entity, user.id)
        db.session.commit()
        return item

    @classmethod
    def available_rows(cls, plan: WorkPlan, rows: list[dict]) -> list[dict]:
        """Убрать из выбора работы текущего и других активных WorkPlan."""
        plan_requests, plan_defects = cls._plan_ids(plan)
        busy_requests, busy_defects = cls._busy_ids(exclude_plan_id=plan.id)
        result = []
        for row in rows:
            entity_type = row.get("entity_type") or row.get("type")
            try:
                entity_id = uuid.UUID(str(row.get("entity_id") or row.get("id") or ""))
            except ValueError:
                continue
            if entity_type == ENTITY_REQUEST and entity_id not in plan_requests | busy_requests:
                result.append(row)
            elif entity_type == ENTITY_DEFECT and entity_id not in plan_defects | busy_defects:
                result.append(row)
        return result

    @classmethod
    def remove_draft_item(cls, plan: WorkPlan, item_id: uuid.UUID, user: User) -> None:
        if plan.status != PLAN_DRAFT:
            raise ValidationError("Из сохранённого плана работу можно только исключить с указанием причины.")
        item = next((row for row in cls._active_items(plan) if row.id == item_id), None)
        if item is None:
            raise NotFoundError("Работа не найдена в плане.")
        number = item.number_snapshot
        item.soft_delete(deleted_by=user.id)
        cls._log(plan, user.id, "remove_item", f"Удалено из черновика: {number}", item_id=item.id)
        plan.updated_by = user.id
        db.session.commit()

    @classmethod
    def save_plan(cls, plan: WorkPlan, user: User) -> WorkPlan:
        if plan.status != PLAN_DRAFT:
            raise ValidationError("Сохранить можно только черновик плана.")
        items = cls._active_items(plan)
        if not items:
            raise ValidationError("Добавьте хотя бы одну работу в план.")
        plan.number = plan.number or cls.next_number()
        plan.status = PLAN_IN_PROGRESS
        plan.saved_at = utcnow()
        plan.updated_by = user.id
        for item in items:
            if item.request_id:
                req = db.session.get(Request, item.request_id)
                if req is None:
                    raise NotFoundError("Заявка из плана не найдена.")
                item.previous_status_code = item.previous_status_code or (
                    req.status.code if req.status else "new"
                )
                RequestService.mark_in_progress_in_session(item.request_id, user.id)
                item.pp_snapshot = req.pp or item.pp_snapshot
            elif item.defect_id:
                defect = db.session.get(Defect, item.defect_id)
                if defect is None:
                    raise NotFoundError("Дефект из плана не найден.")
                previous = defect.status.code if defect.status else DEFECT_OPEN
                DefectService.mark_in_progress_in_session(defect, user.id)
                item.previous_status_code = item.previous_status_code or previous
                item.pp_snapshot = defect.pp or item.pp_snapshot
            item.updated_by = user.id
        cls._log(
            plan,
            user.id,
            "save",
            f"План {plan.number} сохранён, работы переведены «В работе»",
            details={"count": len(items)},
        )
        db.session.commit()
        return cls.get_owned(plan.id, user)

    @classmethod
    def _assert_can_add(cls, entity_type: str, entity_id: uuid.UUID, entity, *, skip_requests, skip_defects) -> None:
        if entity_type == ENTITY_REQUEST:
            if entity_id in skip_requests:
                raise ValidationError("Эта заявка уже есть в плане или в другом активном плане.")
            if entity.status and entity.status.code not in OPEN_STATUS_CODES:
                raise ValidationError("В план можно добавить только незакрытую заявку.")
            return
        if entity_id in skip_defects:
            raise ValidationError("Этот дефект уже есть в плане или в другом активном плане.")
        code = entity.status.code if entity.status else ""
        if code not in {DEFECT_OPEN, DEFECT_IN_PROGRESS}:
            raise ValidationError("В план можно добавить только открытый дефект.")

    @classmethod
    def _build_item(cls, plan: WorkPlan, entity, entity_type: str, user: User, sort_order: int) -> WorkPlanItem:
        description = (entity.description or "") if entity_type == ENTITY_DEFECT else (entity.description or entity.title or "")
        return WorkPlanItem(
            plan_id=plan.id,
            sort_order=sort_order,
            request_id=entity.id if entity_type == ENTITY_REQUEST else None,
            defect_id=entity.id if entity_type == ENTITY_DEFECT else None,
            result=ITEM_ACTIVE,
            number_snapshot=entity.number,
            address_snapshot=entity.address or "",
            pp_snapshot=entity.pp or "",
            description_snapshot=description,
            street_snapshot=entity.street or "",
            district_snapshot=entity.district or "",
            previous_status_code=entity.status.code if entity.status else None,
            created_by=user.id,
            updated_by=user.id,
        )

    @classmethod
    def create_and_start(cls, user: User, raw_items: list[dict]) -> WorkPlan:
        """Создаёт план сразу «В работе». Черновик в БД не пишется."""
        parsed: list[tuple[str, uuid.UUID]] = []
        seen: set[tuple[str, uuid.UUID]] = set()
        for row in raw_items or []:
            entity_type = str(row.get("entity_type") or "").strip()
            try:
                entity_id = uuid.UUID(str(row.get("entity_id") or ""))
            except ValueError:
                continue
            if entity_type not in {ENTITY_REQUEST, ENTITY_DEFECT}:
                continue
            key = (entity_type, entity_id)
            if key in seen:
                continue
            seen.add(key)
            parsed.append(key)
        if not parsed:
            raise ValidationError("Добавьте хотя бы одну работу в план.")

        busy_requests, busy_defects = cls._busy_ids()
        entities = []
        for entity_type, entity_id in parsed:
            entity = cls._load_entity(entity_type, entity_id)
            cls._assert_can_add(
                entity_type,
                entity_id,
                entity,
                skip_requests=busy_requests,
                skip_defects=busy_defects,
            )
            entities.append((entity_type, entity))

        plan = WorkPlan(
            master_id=user.id,
            status=PLAN_IN_PROGRESS,
            number=cls.next_number(),
            saved_at=utcnow(),
            created_by=user.id,
            updated_by=user.id,
        )
        db.session.add(plan)
        db.session.flush()
        cls._log(plan, user.id, "create", f"Создан план работ {plan.number}")
        for index, (entity_type, entity) in enumerate(entities, start=1):
            item = cls._build_item(plan, entity, entity_type, user, index)
            db.session.add(item)
            db.session.flush()
            cls._log(
                plan,
                user.id,
                "add_item",
                f"В план добавлен {entity.number}",
                item_id=item.id,
                details={"entity_type": entity_type, "entity_id": str(entity.id), "number": entity.number},
            )
            if entity_type == ENTITY_REQUEST:
                RequestService.mark_in_progress_in_session(entity.id, user.id)
            else:
                DefectService.mark_in_progress_in_session(entity, user.id)
        cls._log(
            plan,
            user.id,
            "save",
            f"План {plan.number} сохранён, работы переведены «В работе»",
            details={"count": len(entities)},
        )
        db.session.commit()
        return cls.get_owned(plan.id, user)

    @classmethod
    def maybe_complete_plan(cls, plan: WorkPlan, user: User) -> bool:
        items = cls._active_items(plan)
        if not items or plan.status != PLAN_IN_PROGRESS:
            return False
        if any(item.result == ITEM_ACTIVE for item in items):
            return False
        plan.status = PLAN_COMPLETED
        plan.completed_at = utcnow()
        plan.updated_by = user.id
        cls._log(plan, user.id, "complete_plan", f"План {plan.number} завершён автоматически")
        return True

    @classmethod
    def complete_item(
        cls,
        plan: WorkPlan,
        item_id: uuid.UUID,
        user: User,
        *,
        comment: str,
        files: list[FileStorage] | None = None,
    ) -> WorkPlan:
        if plan.status != PLAN_IN_PROGRESS:
            raise ValidationError("Выполнять работы можно в плане со статусом «В работе».")
        item = next((row for row in cls._active_items(plan) if row.id == item_id), None)
        if item is None:
            raise NotFoundError("Работа не найдена в плане.")
        if item.result != ITEM_ACTIVE:
            raise ValidationError("Эта работа уже закрыта в плане.")
        text = (comment or "").strip()
        if not text:
            raise ValidationError("Укажите комментарий о выполнении.")
        uploads = [storage for storage in (files or []) if storage and storage.filename]
        if item.request_id:
            req = db.session.get(Request, item.request_id)
            if req is None:
                raise NotFoundError("Заявка не найдена.")
            if uploads:
                RequestService.add_attachments(req, file_storages=uploads, user_id=user.id)
            RequestService.complete_request(item.request_id, user.id, comment=text, commit=False)
        else:
            defect = db.session.get(Defect, item.defect_id)
            if defect is None:
                raise NotFoundError("Дефект не найден.")
            if uploads:
                DefectService.add_attachments(defect, uploads, user.id)
            DefectService.change_status(defect, DEFECT_FIXED, user.id, comment=text, commit=False)
        now = utcnow()
        item.result = ITEM_COMPLETED
        item.complete_comment = text
        item.completed_at = now
        item.completed_by = user.id
        item.updated_by = user.id
        cls._log(plan, user.id, "complete_item", text, item_id=item.id, details={"number": item.number_snapshot})
        cls.maybe_complete_plan(plan, user)
        db.session.commit()
        return cls.get_owned(plan.id, user)

    @classmethod
    def exclude_item(
        cls,
        plan: WorkPlan,
        item_id: uuid.UUID,
        user: User,
        *,
        reason: str,
        comment: str,
        files: list[FileStorage] | None = None,
    ) -> WorkPlan:
        if plan.status != PLAN_IN_PROGRESS:
            raise ValidationError("Исключать работы можно из плана со статусом «В работе».")
        item = next((row for row in cls._active_items(plan) if row.id == item_id), None)
        if item is None:
            raise NotFoundError("Работа не найдена в плане.")
        if item.result != ITEM_ACTIVE:
            raise ValidationError("Эта работа уже закрыта в плане.")
        reason_code = (reason or "").strip()
        if reason_code not in EXCLUDE_REASON_LABELS:
            raise ValidationError("Укажите причину исключения.")
        text = (comment or "").strip()
        if not text:
            raise ValidationError("Укажите комментарий к исключению.")
        item.result = ITEM_EXCLUDED
        item.exclude_reason = reason_code
        item.exclude_comment = text
        item.excluded_at = utcnow()
        item.excluded_by = user.id
        item.updated_by = user.id
        uploads = [storage for storage in (files or []) if storage and storage.filename]
        if uploads:
            from app.core.upload_utils import UploadValidationError, save_upload

            for storage in uploads:
                try:
                    saved = save_upload(storage, relative_dir=f"work-plans/{plan.id}/exclusions/{item.id}")
                except UploadValidationError as exc:
                    raise ValidationError(str(exc)) from exc
                db.session.add(
                    Attachment(
                        uploaded_by=user.id,
                        entity_type=EntityType.WORK_PLAN_ITEM.value,
                        entity_id=item.id,
                        file_name=saved.file_name,
                        storage_key=saved.storage_key,
                        mime_type=saved.mime_type,
                        file_size=saved.file_size,
                        checksum=None,
                        created_by=user.id,
                        updated_by=user.id,
                    )
                )
        reason_label = EXCLUDE_REASON_LABELS[reason_code]
        history_text = f"Исключена из плана: {reason_label}. {text}"
        if item.request_id:
            req = RequestService._lock_request(item.request_id)
            from app.modules.waybills.services import WaybillService

            if not WaybillService.entity_in_other_active_work(
                request_id=item.request_id, skip_plan_id=plan.id
            ):
                RequestService.restore_from_plan_in_session(
                    item.request_id, user.id, item.previous_status_code
                )
            RequestService._log_history(
                req,
                user.id,
                "exclude_from_plan",
                history_text,
                {"plan_id": str(plan.id), "plan_number": plan.number, "reason": reason_code},
            )
        elif item.defect_id:
            defect = db.session.get(Defect, item.defect_id)
            if defect is not None:
                from app.modules.waybills.services import WaybillService

                if not WaybillService.entity_in_other_active_work(
                    defect_id=item.defect_id, skip_plan_id=plan.id
                ):
                    DefectService.restore_from_plan_in_session(
                        defect, user.id, item.previous_status_code
                    )
                DefectService._log_history(defect, user.id, "exclude_from_plan", history_text, {"plan_id": str(plan.id)})
        cls._log(
            plan,
            user.id,
            "exclude_item",
            history_text,
            item_id=item.id,
            details={"number": item.number_snapshot, "reason": reason_code},
        )
        cls.maybe_complete_plan(plan, user)
        db.session.commit()
        return cls.get_owned(plan.id, user)

    @classmethod
    def my_plans(cls, user: User) -> list[dict]:
        plans = list(
            db.session.scalars(
                select(WorkPlan)
                .options(
                    joinedload(WorkPlan.master),
                    selectinload(WorkPlan.items),
                )
                .where(
                    WorkPlan.master_id == user.id,
                    WorkPlan.active_filter(),
                    WorkPlan.status != PLAN_DRAFT,
                )
                .order_by(
                    case(
                        (WorkPlan.status == PLAN_DRAFT, 0),
                        (WorkPlan.status == PLAN_IN_PROGRESS, 1),
                        else_=2,
                    ),
                    WorkPlan.created_at.desc(),
                )
            ).unique()
        )
        return [cls.serialize_plan_summary(plan) for plan in plans]

    @staticmethod
    def parse_filter_date(value: str | None) -> date | None:
        try:
            return date.fromisoformat((value or "").strip())
        except ValueError:
            return None

    @classmethod
    def tracking(
        cls,
        *,
        status: str = "",
        master_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """Сводка WorkPlan для директорского контроля без изменения планов."""
        conditions = [WorkPlan.active_filter()]
        if status:
            conditions.append(WorkPlan.status == status)
        if master_id is not None:
            conditions.append(WorkPlan.master_id == master_id)

        local_zone = ZoneInfo("Europe/Moscow")
        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=local_zone).astimezone(timezone.utc)
            conditions.append(WorkPlan.created_at >= start)
        if date_to is not None:
            finish = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=local_zone).astimezone(timezone.utc)
            conditions.append(WorkPlan.created_at < finish)

        plans = list(
            db.session.scalars(
                select(WorkPlan)
                .options(joinedload(WorkPlan.master), selectinload(WorkPlan.items))
                .where(*conditions)
                .order_by(
                    case(
                        (WorkPlan.status == PLAN_IN_PROGRESS, 0),
                        (WorkPlan.status == PLAN_DRAFT, 1),
                        else_=2,
                    ),
                    WorkPlan.created_at.desc(),
                )
            ).unique()
        )
        rows = [cls.serialize_plan_summary(plan) for plan in plans]
        masters = list(
            db.session.scalars(
                select(User)
                .join(WorkPlan, WorkPlan.master_id == User.id)
                .where(WorkPlan.active_filter(), User.active_filter(), User.is_active.is_(True))
                .distinct()
                .order_by(User.full_name)
            ).unique()
        )
        return {
            "plans": rows,
            "masters": masters,
            "stats": {
                "total": len(rows),
                "draft": sum(1 for row in rows if row["status"] == PLAN_DRAFT),
                "in_progress": sum(1 for row in rows if row["status"] == PLAN_IN_PROGRESS),
                "completed": sum(1 for row in rows if row["status"] == PLAN_COMPLETED),
                "works": sum(row["total"] for row in rows),
                "done": sum(row["done"] for row in rows),
                "remaining": sum(row["remaining"] for row in rows),
            },
        }

    @classmethod
    def serialize_plan_summary(cls, plan: WorkPlan) -> dict:
        items = cls._active_items(plan)
        done = sum(1 for item in items if item.result == ITEM_COMPLETED)
        excluded = sum(1 for item in items if item.result == ITEM_EXCLUDED)
        return {
            "id": str(plan.id),
            "number": plan.number or "—",
            "status": plan.status,
            "status_label": PLAN_STATUS_LABELS.get(plan.status, plan.status),
            "created_at": cls._fmt_dt(plan.created_at),
            "created_date": cls._fmt_date(plan.created_at),
            "saved_at": cls._fmt_dt(plan.saved_at),
            "completed_at": cls._fmt_dt(plan.completed_at),
            "master": plan.master.full_name if plan.master else "",
            "master_id": str(plan.master_id),
            "total": len(items),
            "done": done,
            "excluded": excluded,
            "active": sum(1 for item in items if item.result == ITEM_ACTIVE),
            "remaining": sum(1 for item in items if item.result == ITEM_ACTIVE),
            "progress_percent": int(round((done + excluded) * 100 / len(items))) if items else 0,
            "editable": False,
        }

    @classmethod
    def serialize_plan(cls, plan: WorkPlan, user: User | None = None) -> dict:
        items = cls._active_items(plan)
        items.sort(key=lambda row: row.sort_order)
        summary = cls.serialize_plan_summary(plan)
        history = []
        for entry in sorted(plan.history or [], key=lambda row: row.created_at or row.id, reverse=True):
            if entry.deleted_at is not None:
                continue
            history.append(
                {
                    "id": str(entry.id),
                    "action": entry.action,
                    "comment": entry.comment or "",
                    "user": entry.changed_by_user.full_name if entry.changed_by_user else "",
                    "created_at": cls._fmt_dt(entry.created_at),
                }
            )
        summary.update(
            {
                "items": [cls.serialize_item(item, plan_status=plan.status) for item in items],
                "history": history,
                "readonly": plan.status == PLAN_COMPLETED,
            }
        )
        return summary

    @classmethod
    def serialize_item(cls, item: WorkPlanItem, user: User | None = None, *, plan_status: str | None = None) -> dict:
        entity = item.request if item.request_id else item.defect
        live_status = ""
        live_status_code = ""
        pp = item.pp_snapshot or ""
        address = item.address_snapshot or ""
        description = item.description_snapshot or ""
        number = item.number_snapshot
        if entity is not None:
            number = entity.number or number
            address = entity.address or address
            pp = (entity.pp or pp) if hasattr(entity, "pp") else pp
            if item.request_id:
                description = entity.description or entity.title or description
            else:
                description = entity.description or description
            if entity.status is not None:
                live_status = entity.status.name
                live_status_code = entity.status.code
        photos = cls._entity_photos(item)
        return {
            "id": str(item.id),
            "entity_type": item.entity_type,
            "entity_id": str(item.request_id or item.defect_id),
            "type_label": "Заявка" if item.entity_type == ENTITY_REQUEST else "Дефект",
            "number": number,
            "address": address,
            "pp": pp,
            "description": description,
            "street": item.street_snapshot or (entity.street if entity is not None else "") or "",
            "district": item.district_snapshot or (entity.district if entity is not None else "") or "",
            "result": item.result,
            "result_label": ITEM_RESULT_LABELS.get(item.result, item.result),
            "status": live_status,
            "status_code": live_status_code,
            "complete_comment": item.complete_comment or "",
            "completed_at": cls._fmt_dt(item.completed_at),
            "completed_by": item.completed_by_user.full_name if item.completed_by_user else "",
            "exclude_reason": item.exclude_reason or "",
            "exclude_reason_label": EXCLUDE_REASON_LABELS.get(item.exclude_reason or "", ""),
            "exclude_comment": item.exclude_comment or "",
            "excluded_at": cls._fmt_dt(item.excluded_at),
            "excluded_by": item.excluded_by_user.full_name if item.excluded_by_user else "",
            "exclusion_files": cls._exclusion_files(item),
            "photos": photos,
            "can_complete": item.result == ITEM_ACTIVE and (plan_status or (item.plan.status if item.plan else "")) == PLAN_IN_PROGRESS,
            "can_exclude": item.result == ITEM_ACTIVE and (plan_status or (item.plan.status if item.plan else "")) == PLAN_IN_PROGRESS,
        }

    @classmethod
    def _exclusion_files(cls, item: WorkPlanItem) -> list[dict]:
        files = db.session.scalars(
            select(Attachment)
            .where(
                Attachment.entity_type == EntityType.WORK_PLAN_ITEM.value,
                Attachment.entity_id == item.id,
                Attachment.active_filter(),
            )
            .order_by(Attachment.created_at.asc())
        )
        return [
            {
                "id": str(file.id),
                "name": file.file_name,
                "url": url_for("work_orders.download_exclusion_attachment", item_id=item.id, attachment_id=file.id, inline=1),
            }
            for file in files
        ]

    @classmethod
    def _entity_photos(cls, item: WorkPlanItem) -> list[dict]:
        entity_type = EntityType.REQUEST.value if item.request_id else EntityType.DEFECT.value
        entity_id = item.request_id or item.defect_id
        if entity_id is None:
            return []
        files = list(
            db.session.scalars(
                select(Attachment)
                .where(
                    Attachment.entity_type == entity_type,
                    Attachment.entity_id == entity_id,
                    Attachment.active_filter(),
                    Attachment.mime_type.ilike("image/%"),
                )
                .order_by(Attachment.created_at.desc())
            )
        )
        photos = []
        for file in files:
            if item.request_id:
                preview = url_for(
                    "requests.download_attachment",
                    request_id=item.request_id,
                    attachment_id=file.id,
                    inline=1,
                )
            else:
                preview = url_for(
                    "defects.download_attachment",
                    defect_id=item.defect_id,
                    attachment_id=file.id,
                    inline=1,
                )
            photos.append(
                {
                    "id": str(file.id),
                    "name": file.file_name,
                    "preview_url": preview,
                }
            )
        return photos

    @classmethod
    def related_works(
        cls,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        plan: WorkPlan | None,
        extra_skip_requests: set[uuid.UUID] | None = None,
        extra_skip_defects: set[uuid.UUID] | None = None,
    ) -> dict:
        source = cls._load_entity(entity_type, entity_id)
        plan_requests, plan_defects = cls._plan_ids(plan) if plan is not None else (set(), set())
        if entity_type == ENTITY_REQUEST:
            plan_requests.add(entity_id)
        else:
            plan_defects.add(entity_id)
        busy_requests, busy_defects = cls._busy_ids(exclude_plan_id=plan.id if plan else None)
        skip_requests = plan_requests | busy_requests | set(extra_skip_requests or ())
        skip_defects = plan_defects | busy_defects | set(extra_skip_defects or ())
        pp_key = normalize_pp(getattr(source, "pp", None))
        street_key = (source.street or "").strip().casefold()
        address_key = (source.address or "").strip().casefold()
        district_key = (source.district or "").strip().casefold()

        by_pp: list[dict] = []
        by_address: list[dict] = []
        by_district: list[dict] = []
        seen_requests: set[uuid.UUID] = set(skip_requests)
        seen_defects: set[uuid.UUID] = set(skip_defects)

        def take(bucket: list[dict], kind: str, rows, predicate) -> None:
            for row in rows:
                if kind == ENTITY_REQUEST:
                    if row.id in seen_requests or not predicate(row):
                        continue
                    seen_requests.add(row.id)
                else:
                    if row.id in seen_defects or not predicate(row):
                        continue
                    seen_defects.add(row.id)
                bucket.append(cls._related_dict(kind, row))
                if len(bucket) >= RELATED_LIMIT:
                    break

        open_requests = cls._open_requests()
        open_defects = cls._open_defects()
        if pp_key:
            take(by_pp, ENTITY_REQUEST, open_requests, lambda row: normalize_pp(row.pp) == pp_key)
            take(by_pp, ENTITY_DEFECT, open_defects, lambda row: normalize_pp(row.pp) == pp_key)
        take(
            by_address,
            ENTITY_REQUEST,
            open_requests,
            lambda row: bool(street_key and (row.street or "").strip().casefold() == street_key)
            or bool(address_key and (row.address or "").strip().casefold() == address_key),
        )
        take(
            by_address,
            ENTITY_DEFECT,
            open_defects,
            lambda row: bool(street_key and (row.street or "").strip().casefold() == street_key)
            or bool(address_key and (row.address or "").strip().casefold() == address_key),
        )
        if district_key:
            take(
                by_district,
                ENTITY_REQUEST,
                open_requests,
                lambda row: (row.district or "").strip().casefold() == district_key,
            )
            take(
                by_district,
                ENTITY_DEFECT,
                open_defects,
                lambda row: (row.district or "").strip().casefold() == district_key,
            )
        pp_label = (source.pp or "").strip() or pp_key
        return {
            "pp": pp_label,
            "pp_key": pp_key,
            "address": source.address or "",
            "street": source.street or "",
            "district": source.district or "",
            "by_pp": by_pp,
            "by_address": by_address,
            "by_district": by_district,
        }

    @classmethod
    def _open_requests(cls) -> list[Request]:
        return list(
            db.session.scalars(
                select(Request)
                .options(joinedload(Request.status), joinedload(Request.journal))
                .join(RequestStatus, Request.status_id == RequestStatus.id)
                .where(Request.active_filter(), RequestStatus.code.in_(tuple(OPEN_STATUS_CODES)))
                .order_by(Request.received_at.desc().nullslast(), Request.created_at.desc())
                .limit(400)
            ).unique()
        )

    @classmethod
    def _open_defects(cls) -> list[Defect]:
        return list(
            db.session.scalars(
                select(Defect)
                .options(joinedload(Defect.status))
                .join(DefectStatus, Defect.status_id == DefectStatus.id)
                .where(Defect.active_filter(), DefectStatus.code.in_((DEFECT_OPEN, DEFECT_IN_PROGRESS)))
                .order_by(Defect.created_at.desc())
                .limit(400)
            ).unique()
        )

    @staticmethod
    def _related_dict(entity_type: str, item) -> dict:
        return {
            "id": str(item.id),
            "entity_type": entity_type,
            "entity_id": str(item.id),
            "type_label": "Заявка" if entity_type == ENTITY_REQUEST else "Дефект",
            "number": item.number,
            "address": item.address or "",
            "pp": item.pp or "",
            "description": (item.description or (item.title if entity_type == ENTITY_REQUEST else "") or "")[:180],
            "status": item.status.name if item.status else "",
            "status_code": item.status.code if item.status else "",
        }
