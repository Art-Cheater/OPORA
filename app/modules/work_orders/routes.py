"""Маршруты рабочего места «Работа по заявкам»."""

from __future__ import annotations

import uuid

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.http import ajax_error, ajax_ok
from app.models.auth.constants import (
    PERM_WAYBILLS_EDIT,
    PERM_WAYBILLS_STATUS_CHANGE,
    PERM_WAYBILLS_VIEW,
)
from app.modules.defects.repositories import DefectRepository
from app.modules.requests.districts import district_choices
from app.modules.requests.repositories import RequestRepository
from app.modules.waybills.services import WaybillService
from app.modules.waybills.workflow import STATUS_DRAFT, STATUS_IN_PROGRESS
from app.modules.work_orders.blueprint import work_orders_bp
from app.modules.work_orders.services import WorkOrderFilter, WorkOrderService


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _filters_from_request() -> WorkOrderFilter:
    kind = (request.args.get("kind") or "all").strip().lower()
    if kind not in {"all", "request", "defect"}:
        kind = "all"
    active_raw = (request.args.get("active_only") or "1").strip().lower()
    return WorkOrderFilter(
        kind=kind,
        q=request.args.get("q") or "",
        district=request.args.get("district") or "",
        journal_id=request.args.get("journal_id") or "",
        status_id=request.args.get("status_id") or "",
        responsible_id=(
            str(current_user.id)
            if (request.args.get("mine") or "").strip().lower() in {"1", "true", "yes"}
            else (request.args.get("responsible_id") or "")
        ),
        work_date=request.args.get("date") or "",
        active_only=active_raw not in {"0", "false", "no"},
    )


def _current_plan():
    return WorkOrderService.today_plan(current_user.id)


@work_orders_bp.route("/")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def index():
    return render_template(
        "work_orders/index.html",
        journals=WorkOrderService.journals(),
        request_statuses=RequestRepository.get_statuses(),
        defect_statuses=DefectRepository.get_statuses(),
        districts=district_choices(empty_label="Все районы"),
        can_edit=current_user.has_permission(PERM_WAYBILLS_EDIT),
        can_complete=current_user.has_permission(PERM_WAYBILLS_STATUS_CHANGE),
    )


@work_orders_bp.route("/map.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def map_json():
    plan = _current_plan()
    points = WorkOrderService.map_points(_filters_from_request(), plan)
    return jsonify({"points": points, "remaining": 0})


@work_orders_bp.route("/items.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def items_json():
    plan = _current_plan()
    return jsonify({"items": WorkOrderService.list_items(_filters_from_request(), plan)})


@work_orders_bp.route("/plan.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def plan_json():
    return jsonify(WorkOrderService.serialize_plan(_current_plan()))


@work_orders_bp.route("/route.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def route_json():
    plan = _current_plan()
    payload = WorkOrderService.serialize_plan(plan)
    points = [
        {
            "id": stop["id"],
            "order": stop["order"],
            "address": stop["address"],
            "lat": stop["lat"],
            "lng": stop["lng"],
            "type": stop["entity_type"],
            "number": stop["number"],
        }
        for stop in payload["stops"]
        if stop["lat"] is not None and stop["lng"] is not None
    ]
    return jsonify({"points": points, "remaining": 0})


@work_orders_bp.route("/nearby.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def nearby_json():
    entity_type = (request.args.get("entity_type") or "").strip()
    entity_id = _uuid_or_none(request.args.get("entity_id"))
    if entity_id is None or entity_type not in {"request", "defect"}:
        return jsonify({"hits": [], "summary": ""})
    hits, summary = WorkOrderService.nearby_for(entity_type, entity_id, _current_plan())
    return jsonify({"summary": summary, "hits": [WorkOrderService.hit_to_dict(h) for h in hits]})


@work_orders_bp.route("/plan/add", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plan_add():
    payload = request.get_json(silent=True) or request.form
    entity_type = (payload.get("entity_type") or "").strip()
    entity_id = _uuid_or_none(payload.get("entity_id"))
    if entity_id is None or entity_type not in {"request", "defect"}:
        return ajax_error("Выберите заявку или дефект.")
    try:
        plan = WorkOrderService.get_or_create_today_draft(current_user)
        WaybillService.add_stop(plan, entity_type=entity_type, entity_id=entity_id, user_id=current_user.id)
        plan = WorkOrderService.today_plan(current_user.id)
        hits, summary = WorkOrderService.nearby_for(entity_type, entity_id, plan)
        return ajax_ok(
            "Добавлено в план.",
            plan=WorkOrderService.serialize_plan(plan),
            nearby={"summary": summary, "hits": [WorkOrderService.hit_to_dict(h) for h in hits]},
        )
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plan/remove", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plan_remove():
    payload = request.get_json(silent=True) or request.form
    stop_id = _uuid_or_none(payload.get("stop_id"))
    plan = _current_plan()
    if plan is None or stop_id is None:
        return ajax_error("Точка не найдена.", status=404)
    try:
        WaybillService.remove_stop(plan, stop_id, current_user.id)
        plan = WorkOrderService.today_plan(current_user.id)
        return ajax_ok("Удалено из плана.", plan=WorkOrderService.serialize_plan(plan))
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plan/reorder", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plan_reorder():
    payload = request.get_json(silent=True) or request.form
    ids = payload.get("stop_ids") or payload.getlist("stop_ids[]") or payload.getlist("stop_ids")
    parsed = [_uuid_or_none(v) for v in ids]
    plan = _current_plan()
    if plan is None:
        return ajax_error("План ещё не создан.", status=404)
    if any(v is None for v in parsed):
        return ajax_error("Некорректный список.")
    try:
        WaybillService.reorder_stops(plan, parsed, current_user.id)
        plan = WorkOrderService.today_plan(current_user.id)
        return ajax_ok("Порядок сохранён.", plan=WorkOrderService.serialize_plan(plan))
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plan/save", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plan_save():
    plan = _current_plan()
    if plan is None or not any(s.deleted_at is None for s in plan.stops):
        return ajax_error("Добавьте хотя бы одну работу в план.")
    if plan.status == STATUS_DRAFT and current_user.has_permission(PERM_WAYBILLS_STATUS_CHANGE):
        try:
            WaybillService.change_status(plan, STATUS_IN_PROGRESS, current_user.id)
        except ValidationError as exc:
            return ajax_error(str(exc))
        plan = WorkOrderService.today_plan(current_user.id)
    payload = WorkOrderService.serialize_plan(plan)
    label = payload.get("status_label") or ""
    return ajax_ok(
        f"Путевой лист {plan.number} сохранён" + (f" · {label}." if label else "."),
        plan=payload,
    )


@work_orders_bp.route("/plan/complete", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_STATUS_CHANGE)
def plan_complete():
    plan = _current_plan()
    if plan is None or not any(s.deleted_at is None for s in plan.stops):
        return ajax_error("Нет активного плана для завершения.")
    try:
        WaybillService.complete(plan, current_user.id)
    except ValidationError as exc:
        return ajax_error(str(exc))
    closed = WorkOrderService.serialize_plan(None)
    return ajax_ok(
        "Путевой лист завершён. Входящие дефекты отмечены как выполненные.",
        plan=closed,
        completed=True,
    )
