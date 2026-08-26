"""Репозитории модуля заявок."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_
from sqlalchemy.orm import contains_eager, joinedload, load_only, noload

from app.extensions import db
from app.models.auth.associations import UserRole
from app.models.auth.position import Position
from app.models.auth.role import Role
from app.models.auth.user import User
from app.models.requests.request import Request
from app.models.requests.request_dispatcher import RequestDispatcher
from app.models.requests.request_status import RequestStatus
from app.modules.requests.address_format import normalize_address
from app.modules.requests.workflow import (
    PRESET_AWAITING_MASTER,
    PRESET_COMPLETED,
    PRESET_FOR_EMERGENCY,
    PRESET_IN_PROGRESS,
    PRESET_MY,
    STATUS_ACCEPTED_BY_MASTER,
    STATUS_COMPLETED,
    STATUS_EMERGENCY_DISPATCHED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
)


@dataclass
class RequestFilter:
    q: str = ""
    district: str = ""
    pp: str = ""
    for_beresnev: bool = False
    status_id: str = ""
    priority: str = ""
    responsible_id: str = ""
    dispatcher_name: str = ""
    executor_id: str = ""
    preset: str = ""
    sort_by: str = "received_at"
    sort_dir: str = "desc"


class RequestRepository:
    """Чтение и запись заявок."""

    SORT_FIELDS = {
        "created_at": Request.created_at,
        "updated_at": Request.updated_at,
        "received_at": Request.received_at,
        "number": Request.number,
        "priority": Request.priority,
        "address": Request.address,
        "title": Request.title,
        "pp": Request.pp,
        "dispatcher_name": Request.dispatcher_name,
        "status_id": Request.status_id,
    }

    @staticmethod
    def get_by_id(request_id: uuid.UUID | str) -> Request | None:
        if isinstance(request_id, str):
            try:
                request_id = uuid.UUID(request_id)
            except ValueError:
                return None
        return db.session.scalar(
            db.select(Request)
            .options(joinedload(Request.status))
            .where(Request.id == request_id, Request.active_filter())
        )

    @staticmethod
    def _address_lookup_tokens(address: str) -> list[str]:
        """Характерные фрагменты для SQL-фильтра, без полной загрузки открытых заявок."""
        tokens: list[str] = []
        formatted = " ".join((address or "").split())
        if not formatted:
            return tokens
        house = None
        house_match = re.search(
            r"(?:дом|д\.?)\s*(\d+[а-яёa-z]?(?:\s*/\s*\d+[а-яёa-z]?)?)\s*$",
            formatted,
            flags=re.IGNORECASE,
        )
        if house_match:
            house = house_match.group(1).replace(" ", "")
        elif (digits := re.search(r"(\d+[а-яёa-z]?)$", formatted, flags=re.IGNORECASE)):
            house = digits.group(1)
        words = [
            part
            for part in re.split(r"[^\wа-яё]+", formatted, flags=re.IGNORECASE)
            if len(part) >= 4 and part.casefold() not in {"киров", "улица", "город"}
        ]
        if words:
            tokens.append(words[-1][:80])
        if house:
            tokens.append(house[:30])
        return tokens

    @classmethod
    def find_open_by_address(
        cls,
        address: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> Request | None:
        """Открытая (не финальная) заявка с тем же нормализованным адресом."""
        target = normalize_address(address)
        if not target:
            return None

        stmt = (
            db.select(Request)
            .join(RequestStatus, Request.status_id == RequestStatus.id)
            .options(
                load_only(
                    Request.id,
                    Request.number,
                    Request.address,
                    Request.received_at,
                    Request.repeat_count,
                    Request.status_id,
                ),
                contains_eager(Request.status),
            )
            .where(
                Request.active_filter(),
                RequestStatus.active_filter(),
                RequestStatus.is_final.is_(False),
            )
            .order_by(Request.received_at.desc().nullslast(), Request.created_at.desc())
            .limit(50)
        )
        tokens = cls._address_lookup_tokens(address)
        if tokens:
            stmt = stmt.where(
                or_(
                    *[
                        func.lower(Request.address).like(f"%{token.casefold()}%")
                        for token in tokens
                    ]
                )
            )
        if exclude_id is not None:
            stmt = stmt.where(Request.id != exclude_id)

        for req in db.session.scalars(stmt).unique():
            if normalize_address(req.address) == target:
                return req
        return None

    @staticmethod
    def get_statuses() -> list[RequestStatus]:
        return list(
            db.session.scalars(
                db.select(RequestStatus)
                .where(RequestStatus.active_filter(), RequestStatus.is_active.is_(True))
                .order_by(RequestStatus.sort_order.asc(), RequestStatus.name.asc())
            )
        )

    @staticmethod
    def get_status_by_code(code: str) -> RequestStatus | None:
        return db.session.scalar(
            db.select(RequestStatus).where(
                RequestStatus.code == code,
                RequestStatus.active_filter(),
                RequestStatus.is_active.is_(True),
            )
        )

    @staticmethod
    def get_users():
        from app.modules.auth.repositories import UserRepository

        return UserRepository.list_active_names()

    @staticmethod
    def get_masters() -> list[User]:
        """Активные сотрудники с должностью или ролью «Мастер»."""
        position_ids = db.select(Position.id).where(
            Position.code == "master",
            Position.active_filter(),
            Position.is_active.is_(True),
        )
        role_user_ids = (
            db.select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                Role.code == "master",
                Role.active_filter(),
                UserRole.active_filter(),
            )
        )
        return list(
            db.session.scalars(
                db.select(User)
                .options(
                    load_only(
                        User.id,
                        User.full_name,
                        User.email,
                        User.is_active,
                        User.is_blocked,
                        User.deleted_at,
                        User.position_id,
                    ),
                    noload(User.user_roles),
                    noload(User.login_logs),
                )
                .where(
                    User.active_filter(),
                    User.is_active.is_(True),
                    User.is_blocked.is_(False),
                    or_(User.position_id.in_(position_ids), User.id.in_(role_user_ids)),
                )
                .order_by(User.full_name.asc())
            )
        )

    @staticmethod
    def get_dispatchers() -> list[RequestDispatcher]:
        return list(
            db.session.scalars(
                db.select(RequestDispatcher)
                .where(
                    RequestDispatcher.active_filter(),
                    RequestDispatcher.is_active.is_(True),
                )
                .order_by(RequestDispatcher.sort_order.asc(), RequestDispatcher.name.asc())
            )
        )

    @staticmethod
    def list_dispatchers_all() -> list[RequestDispatcher]:
        return list(
            db.session.scalars(
                db.select(RequestDispatcher)
                .where(RequestDispatcher.active_filter())
                .order_by(RequestDispatcher.sort_order.asc(), RequestDispatcher.name.asc())
            )
        )

    @staticmethod
    def get_dispatcher(dispatcher_id: uuid.UUID) -> RequestDispatcher | None:
        return db.session.scalar(
            db.select(RequestDispatcher).where(
                RequestDispatcher.id == dispatcher_id,
                RequestDispatcher.active_filter(),
            )
        )

    @staticmethod
    def create_dispatcher(*, name: str, sort_order: int, is_active: bool, user_id: uuid.UUID) -> RequestDispatcher:
        item = RequestDispatcher(
            name=name.strip(),
            sort_order=sort_order or 0,
            is_active=bool(is_active),
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(item)
        db.session.commit()
        return item

    @staticmethod
    def update_dispatcher(
        item: RequestDispatcher,
        *,
        name: str,
        sort_order: int,
        is_active: bool,
        user_id: uuid.UUID,
    ) -> RequestDispatcher:
        item.name = name.strip()
        item.sort_order = sort_order or 0
        item.is_active = bool(is_active)
        item.updated_by = user_id
        db.session.commit()
        return item

    @staticmethod
    def delete_dispatcher(item: RequestDispatcher, user_id: uuid.UUID) -> None:
        item.soft_delete(user_id)
        db.session.commit()

    @staticmethod
    def next_number() -> str:
        """Номер вида YY-N: 25-1, 25-149, 26-1…"""
        from datetime import datetime

        year_yy = datetime.now().year % 100
        prefix = f"{year_yy}-"
        pattern = re.compile(rf"^{year_yy}-(\d+)$")
        numbers = db.session.scalars(
            db.select(Request.number).where(
                Request.number.like(f"{prefix}%"),
                Request.active_filter(),
            )
        ).all()
        max_seq = 0
        for raw in numbers:
            match = pattern.fullmatch((raw or "").strip())
            if match:
                max_seq = max(max_seq, int(match.group(1)))
        return f"{prefix}{max_seq + 1}"

    @classmethod
    def _number_sort_keys(cls):
        """Ключи сортировки для номеров вида 25-149 (год, порядковый номер)."""
        from sqlalchemy import Integer, case, cast

        number = Request.number
        dialect = db.session.get_bind().dialect.name
        if dialect == "postgresql":
            part1 = func.split_part(number, "-", 1)
            part2 = func.split_part(number, "-", 2)
            part3 = func.split_part(number, "-", 3)
            # 25-149 → year=25, seq=149; REQ-2025-001 → year=2025, seq=1
            year_expr = cast(
                case((part3 != "", part2), else_=part1),
                Integer,
            )
            seq_expr = cast(
                case((part3 != "", part3), else_=part2),
                Integer,
            )
        else:
            # SQLite: первые два сегмента через instr
            dash1 = func.instr(number, "-")
            rest = func.substr(number, dash1 + 1)
            dash2 = func.instr(rest, "-")
            year_expr = cast(
                case(
                    (dash2 > 0, func.substr(rest, 1, dash2 - 1)),
                    else_=func.substr(number, 1, dash1 - 1),
                ),
                Integer,
            )
            seq_expr = cast(
                case(
                    (dash2 > 0, func.substr(rest, dash2 + 1)),
                    else_=rest,
                ),
                Integer,
            )
        return year_expr, seq_expr, number

    @classmethod
    def _apply_preset(cls, stmt, preset: str, current_user_id: uuid.UUID | None):
        if not preset:
            return stmt

        if preset == PRESET_FOR_EMERGENCY:
            # Новые заявки (ожидают отметки выезда бригады)
            status = cls.get_status_by_code(STATUS_NEW)
            if status is None:
                return stmt.where(sa_false())
            return stmt.where(Request.status_id == status.id)

        if preset == PRESET_AWAITING_MASTER:
            # Жёлтые: выехала бригада, ещё не переданы мастеру
            status = cls.get_status_by_code(STATUS_EMERGENCY_DISPATCHED)
            if status is None:
                return stmt.where(sa_false())
            return stmt.where(Request.status_id == status.id)

        if preset == PRESET_MY and current_user_id is not None:
            return stmt.where(Request.responsible_id == current_user_id)

        if preset == PRESET_IN_PROGRESS:
            codes = (STATUS_ACCEPTED_BY_MASTER, STATUS_IN_PROGRESS)
            status_ids = db.select(RequestStatus.id).where(
                RequestStatus.code.in_(codes),
                RequestStatus.active_filter(),
            )
            q = stmt.where(Request.status_id.in_(status_ids))
            if current_user_id is not None:
                q = q.where(Request.responsible_id == current_user_id)
            return q

        if preset == PRESET_COMPLETED:
            status = cls.get_status_by_code(STATUS_COMPLETED)
            if status is None:
                return stmt.where(sa_false())
            q = stmt.where(Request.status_id == status.id)
            if current_user_id is not None:
                q = q.where(Request.responsible_id == current_user_id)
            return q

        return stmt

    @classmethod
    def paginated_list(
        cls,
        filters: RequestFilter,
        page: int = 1,
        per_page: int = 20,
        current_user_id: uuid.UUID | None = None,
    ):
        stmt = (
            db.select(Request)
            .where(Request.active_filter())
            .join(Request.status)
            .options(
                load_only(
                    Request.id,
                    Request.number,
                    Request.address,
                    Request.district,
                    Request.pp,
                    Request.dispatcher_name,
                    Request.received_at,
                    Request.created_at,
                    Request.repeat_count,
                    Request.repeat_dates,
                    Request.has_barrier,
                    Request.barrier_phone,
                    Request.for_beresnev,
                    Request.applicant_name,
                    Request.status_id,
                    Request.priority,
                    Request.title,
                ),
                contains_eager(Request.status),
                noload(Request.responsible),
                noload(Request.executor),
                noload(Request.history),
                noload(Request.materials),
                noload(Request.project),
            )
        )

        if filters.q:
            q = f"%{filters.q.strip()}%"
            stmt = stmt.where(
                or_(
                    Request.number.ilike(q),
                    Request.title.ilike(q),
                    Request.address.ilike(q),
                    Request.pp.ilike(q),
                    Request.dispatcher_name.ilike(q),
                    Request.applicant_name.ilike(q),
                    Request.phone.ilike(q),
                )
            )

        if filters.district:
            stmt = stmt.where(Request.district.ilike(f"%{filters.district.strip()}%"))

        if filters.pp:
            stmt = stmt.where(Request.pp.ilike(f"%{filters.pp.strip()}%"))

        if filters.for_beresnev:
            stmt = stmt.where(Request.for_beresnev.is_(True))

        if filters.status_id:
            try:
                stmt = stmt.where(Request.status_id == uuid.UUID(filters.status_id))
            except ValueError:
                pass

        if filters.priority:
            stmt = stmt.where(Request.priority == filters.priority)

        if filters.responsible_id:
            try:
                stmt = stmt.where(Request.responsible_id == uuid.UUID(filters.responsible_id))
            except ValueError:
                pass

        if filters.dispatcher_name:
            stmt = stmt.where(Request.dispatcher_name == filters.dispatcher_name)

        if filters.executor_id:
            try:
                stmt = stmt.where(Request.executor_id == uuid.UUID(filters.executor_id))
            except ValueError:
                pass

        stmt = cls._apply_preset(stmt, filters.preset, current_user_id)

        if filters.sort_by == "number":
            year_key, seq_key, number_key = cls._number_sort_keys()
            if filters.sort_dir == "desc":
                stmt = stmt.order_by(year_key.desc(), seq_key.desc(), number_key.desc())
            else:
                stmt = stmt.order_by(year_key.asc(), seq_key.asc(), number_key.asc())
        else:
            sort_col = cls.SORT_FIELDS.get(filters.sort_by, Request.created_at)
            sort_expr = sort_col.desc() if filters.sort_dir == "desc" else sort_col.asc()
            stmt = stmt.order_by(sort_expr, Request.created_at.desc())

        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)


def sa_false():
    """Условие, которое никогда не выполняется."""
    return Request.id.is_(None)
