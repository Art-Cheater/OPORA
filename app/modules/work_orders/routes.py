"""Маршруты рабочего места «Работа по заявкам»."""

from __future__ import annotations

import uuid

from flask import abort, jsonify, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.decorators import any_permission_required, permission_required
from app.core.exceptions import NotFoundError, ValidationError
from app.core.http import ajax_error, ajax_ok
from app.models.auth.constants import (
    PERM_DEFECTS_EDIT,
    PERM_DEFECTS_STATUS_CHANGE,
    PERM_REQUESTS_APPROVE,
    PERM_REQUESTS_DISPATCH,
    PERM_REQUESTS_EDIT,
    PERM_WAYBILLS_EDIT,
    PERM_WAYBILLS_STATUS_CHANGE,
    PERM_WAYBILLS_VIEW,
)
from app.modules.defects.services import DefectService
from app.modules.defects.workflow import STATUS_FIXED
from app.modules.requests.repositories import RequestRepository
from app.modules.requests.services import RequestService
from app.modules.waybills.services import WaybillService
from app.modules.waybills.workflow import STATUS_DRAFT, STATUS_IN_PROGRESS
from app.modules.work_orders.blueprint import work_orders_bp
from app.modules.work_orders.plan_service import EXCLUDE_REASONS, WorkPlanService
from app.modules.work_orders.services import WorkOrderFilter, WorkOrderService


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _filters_from_request() -> WorkOrderFilter:
    raw_kind = (request.args.get("kind") or request.args.get("work_type") or "all").strip().lower()
    kind_map = {
        "all": "all",
        "request": "request",
        "requests": "request",
        "defect": "defect",
        "defects": "defect",
        "villages": "villages",
        "village": "villages",
    }
    kind = kind_map.get(raw_kind, "all")
    active_raw = (request.args.get("active_only") or "1").strip().lower()
    return WorkOrderFilter(
        kind=kind,
        q=request.args.get("q") or "",
        pp=request.args.get("pp") or "",
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
    from app.modules.requests.districts import district_choices

    can_complete = (
        current_user.has_permission(PERM_REQUESTS_EDIT)
        or current_user.has_permission(PERM_REQUESTS_APPROVE)
        or current_user.has_permission(PERM_REQUESTS_DISPATCH)
    )
    can_complete_defect = (
        current_user.has_permission(PERM_DEFECTS_EDIT)
        or current_user.has_permission(PERM_DEFECTS_STATUS_CHANGE)
    )
    can_edit_plan = current_user.has_permission(PERM_WAYBILLS_EDIT)
    return render_template(
        "work_orders/index.html",
        can_complete=can_complete,
        can_complete_defect=can_complete_defect,
        can_manage_plans=can_edit_plan,
        can_edit_plan=can_edit_plan,
        can_complete_waybill=current_user.has_permission(PERM_WAYBILLS_STATUS_CHANGE),
        journals=RequestRepository.get_journals(),
        districts=district_choices(empty_label="Все районы"),
    )


@work_orders_bp.route("/queue.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def queue_json():
    preset = (request.args.get("preset") or "all").strip().lower()
    if preset not in WorkOrderService.QUEUE_PRESETS:
        preset = "all"
    page = request.args.get("page", 1, type=int)
    return jsonify(
        WorkOrderService.queue(
            preset=preset,
            q=request.args.get("q") or "",
            page=page,
            user=current_user,
            journal=request.args.get("journal") or "all",
            open_only=(request.args.get("open_only") or "").strip().lower() in {"1", "true", "yes"},
        )
    )


@work_orders_bp.route("/requests/<uuid:request_id>.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def request_card_json(request_id: uuid.UUID):
    card = WorkOrderService.card(request_id, current_user)
    if card is None:
        return ajax_error("Заявка не найдена.", status=404)
    return jsonify(card)


@work_orders_bp.route("/requests/<uuid:request_id>/complete", methods=["POST"])
@login_required
@any_permission_required(PERM_REQUESTS_EDIT, PERM_REQUESTS_APPROVE, PERM_REQUESTS_DISPATCH)
def complete_request(request_id: uuid.UUID):
    try:
        req = RequestService.complete_request(request_id, current_user.id)
        return ajax_ok(
            "Заявка отмечена выполненной.",
            item=WorkOrderService.serialize_queue_item(req, current_user),
            card=WorkOrderService.card(req.id, current_user),
        )
    except NotFoundError as exc:
        return ajax_error(str(exc), status=404)
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/defects/<uuid:defect_id>.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def defect_card_json(defect_id: uuid.UUID):
    card = WorkOrderService.defect_card(defect_id, current_user)
    if card is None:
        return ajax_error("Дефект не найден.", status=404)
    return jsonify(card)


@work_orders_bp.route("/defects/<uuid:defect_id>/complete", methods=["POST"])
@login_required
@any_permission_required(PERM_DEFECTS_EDIT, PERM_DEFECTS_STATUS_CHANGE)
def complete_defect(defect_id: uuid.UUID):
    from app.extensions import db
    from app.models.defects.defect import Defect

    item = db.session.get(Defect, defect_id)
    if item is None or item.deleted_at is not None:
        return ajax_error("Дефект не найден.", status=404)
    try:
        DefectService.change_status(item, STATUS_FIXED, current_user.id, comment="Дефект отмечен выполненным")
        return ajax_ok(
            "Дефект отмечен выполненным.",
            item=WorkOrderService.serialize_defect_queue_item(item, current_user),
            card=WorkOrderService.defect_card(item.id, current_user),
        )
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plans/")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def plans_index():
    return render_template(
        "work_orders/plans_index.html",
        plans=WorkPlanService.my_plans(current_user),
        can_manage_plans=current_user.has_permission(PERM_WAYBILLS_EDIT),
    )


@work_orders_bp.route("/plans/new")
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plans_new():
    from app.models.base import format_local_dt, utcnow
    from app.modules.requests.districts import district_choices

    return render_template(
        "work_orders/plans_new.html",
        master_name=current_user.full_name,
        created_label=format_local_dt(utcnow(), "%d.%m.%Y"),
        districts=district_choices(empty_label="Все районы"),
    )


@work_orders_bp.route("/plans/", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plans_create():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    try:
        plan = WorkPlanService.create_and_start(current_user, items)
        return ajax_ok(
            f"План {plan.number} сохранён. Работы переведены «В работе».",
            plan=WorkPlanService.serialize_plan(plan, current_user),
            redirect=url_for("work_orders.plan_page", plan_id=plan.id),
        )
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plans.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def plans_json():
    return jsonify({"plans": WorkPlanService.my_plans(current_user)})


@work_orders_bp.route("/plans/draft", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plans_draft():
    return ajax_ok(
        "Создание плана перенесено на отдельную страницу.",
        redirect=url_for("work_orders.plans_new"),
    )


@work_orders_bp.route("/plans/<uuid:plan_id>.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def plan_detail_json(plan_id: uuid.UUID):
    try:
        plan = WorkPlanService.get_owned(plan_id, current_user)
        return jsonify(WorkPlanService.serialize_plan(plan, current_user))
    except NotFoundError as exc:
        return ajax_error(str(exc), status=404)
    except ValidationError as exc:
        return ajax_error(str(exc), status=403)


@work_orders_bp.route("/plans/<uuid:plan_id>")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def plan_page(plan_id: uuid.UUID):
    try:
        plan = WorkPlanService.get_owned(plan_id, current_user)
    except NotFoundError:
        abort(404)
    except ValidationError:
        abort(403)
    payload = WorkPlanService.serialize_plan(plan, current_user)
    percent = int(round((payload["done"] + payload["excluded"]) * 100 / payload["total"])) if payload["total"] else 0
    return render_template(
        "work_orders/plan_detail.html",
        plan=payload,
        works=payload["items"],
        percent=percent,
        exclude_reasons=EXCLUDE_REASONS,
        can_manage_plans=current_user.has_permission(PERM_WAYBILLS_EDIT) and payload["status"] == "in_progress",
    )


@work_orders_bp.route("/plans/<uuid:plan_id>/items", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plan_add_item(plan_id: uuid.UUID):
    payload = request.get_json(silent=True) or request.form
    entity_type = (payload.get("entity_type") or "").strip()
    entity_id = _uuid_or_none(payload.get("entity_id"))
    if entity_id is None or entity_type not in {"request", "defect"}:
        return ajax_error("Выберите заявку или дефект.")
    try:
        plan = WorkPlanService.get_owned(plan_id, current_user)
        WorkPlanService.add_item(plan, entity_type=entity_type, entity_id=entity_id, user=current_user)
        plan = WorkPlanService.get_owned(plan_id, current_user)
        related = WorkPlanService.related_works(entity_type=entity_type, entity_id=entity_id, plan=plan)
        return ajax_ok(
            "Добавлено в план.",
            plan=WorkPlanService.serialize_plan(plan, current_user),
            related=related,
        )
    except NotFoundError as exc:
        return ajax_error(str(exc), status=404)
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plans/<uuid:plan_id>/items/<uuid:item_id>", methods=["DELETE", "POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def plan_remove_draft_item(plan_id: uuid.UUID, item_id: uuid.UUID):
    payload = request.get_json(silent=True) or request.form or {}
    if request.method == "POST" and (payload.get("action") or request.args.get("action") or "") != "remove":
        return ajax_error("Некорректное действие.")
    try:
        plan = WorkPlanService.get_owned(plan_id, current_user)
        WorkPlanService.remove_draft_item(plan, item_id, current_user)
        plan = WorkPlanService.get_owned(plan_id, current_user)
        return ajax_ok("Удалено из черновика.", plan=WorkPlanService.serialize_plan(plan, current_user))
    except NotFoundError as exc:
        return ajax_error(str(exc), status=404)
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plans/<uuid:plan_id>/save", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def work_plan_save(plan_id: uuid.UUID):
    try:
        plan = WorkPlanService.get_owned(plan_id, current_user)
        plan = WorkPlanService.save_plan(plan, current_user)
        return ajax_ok(
            f"План {plan.number} сохранён. Работы переведены «В работе».",
            plan=WorkPlanService.serialize_plan(plan, current_user),
        )
    except NotFoundError as exc:
        return ajax_error(str(exc), status=404)
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plans/<uuid:plan_id>/items/<uuid:item_id>/complete", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def work_plan_complete_item(plan_id: uuid.UUID, item_id: uuid.UUID):
    payload = request.get_json(silent=True) or {}
    comment = request.form.get("comment") if request.form else None
    if comment is None:
        comment = payload.get("comment") or ""
    files = request.files.getlist("files") if request.files else []
    try:
        plan = WorkPlanService.get_owned(plan_id, current_user)
        plan = WorkPlanService.complete_item(
            plan,
            item_id,
            current_user,
            comment=comment or "",
            files=files,
        )
        return ajax_ok("Работа выполнена.", plan=WorkPlanService.serialize_plan(plan, current_user))
    except NotFoundError as exc:
        return ajax_error(str(exc), status=404)
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/plans/<uuid:plan_id>/items/<uuid:item_id>/exclude", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def work_plan_exclude_item(plan_id: uuid.UUID, item_id: uuid.UUID):
    payload = request.get_json(silent=True) or request.form
    try:
        plan = WorkPlanService.get_owned(plan_id, current_user)
        plan = WorkPlanService.exclude_item(
            plan,
            item_id,
            current_user,
            reason=payload.get("reason") or "",
            comment=payload.get("comment") or "",
        )
        return ajax_ok("Работа исключена из плана.", plan=WorkPlanService.serialize_plan(plan, current_user))
    except NotFoundError as exc:
        return ajax_error(str(exc), status=404)
    except ValidationError as exc:
        return ajax_error(str(exc))


@work_orders_bp.route("/related.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def related_json():
    entity_type = (request.args.get("entity_type") or "").strip()
    entity_id = _uuid_or_none(request.args.get("entity_id"))
    plan_id = _uuid_or_none(request.args.get("plan_id"))
    empty = {"pp": "", "by_pp": [], "by_address": [], "by_district": []}
    if entity_id is None or entity_type not in {"request", "defect"}:
        return jsonify(empty)
    plan = None
    if plan_id is not None:
        try:
            plan = WorkPlanService.get_owned(plan_id, current_user)
        except (NotFoundError, ValidationError):
            plan = None
    extra_skip_requests = {_uuid_or_none(value) for value in request.args.getlist("skip_request")}
    extra_skip_defects = {_uuid_or_none(value) for value in request.args.getlist("skip_defect")}
    extra_skip_requests.discard(None)
    extra_skip_defects.discard(None)
    try:
        return jsonify(
            WorkPlanService.related_works(
                entity_type=entity_type,
                entity_id=entity_id,
                plan=plan,
                extra_skip_requests=extra_skip_requests,
                extra_skip_defects=extra_skip_defects,
            )
        )
    except (NotFoundError, ValidationError):
        return jsonify(empty)


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
