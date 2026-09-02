"""Маршруты путевых листов."""

from __future__ import annotations

import uuid
from datetime import date

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.field_permissions import FieldPermissionService
from app.core.forms_utils import form_errors_message
from app.core.http import ajax_error, ajax_ok, is_ajax
from app.extensions import db
from app.models.auth.constants import (
    PERM_WAYBILLS_CREATE,
    PERM_WAYBILLS_DELETE,
    PERM_WAYBILLS_EDIT,
    PERM_WAYBILLS_STATUS_CHANGE,
    PERM_WAYBILLS_VIEW,
)
from app.models.auth.user import User
from app.models.defects.defect import Defect
from app.models.requests.request import Request
from app.modules.waybills.blueprint import waybills_bp
from app.modules.waybills.forms import WaybillFilterForm, WaybillForm, WaybillStatusForm, WaybillStopForm
from app.modules.waybills.repositories import WaybillFilter, WaybillRepository
from app.modules.waybills.services import WaybillPayload, WaybillService
from app.modules.waybills.workflow import WAYBILL_STATUSES, can_transition, row_status_class, status_label


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _prepare_form(form: WaybillForm) -> None:
    masters = WaybillRepository.get_masters()
    form.master_id.choices = [(str(u.id), u.full_name) for u in masters]
    users = list(db.session.scalars(db.select(User).where(User.active_filter(), User.is_active.is_(True)).order_by(User.full_name)))
    form.member_ids.choices = [(str(u.id), u.full_name) for u in users]


def _payload(form: WaybillForm, entity=None) -> WaybillPayload:
    fp = FieldPermissionService.resolve_field
    u, m = current_user, "waybills"
    master_raw = fp(u, m, "master_id", form.master_id.data, entity)
    members_raw = fp(u, m, "member_ids", form.member_ids.data, entity) or []
    if isinstance(members_raw, str):
        members_raw = [members_raw]
    return WaybillPayload(
        number=fp(u, m, "number", form.number.data, entity) or form.number.data,
        work_date=fp(u, m, "work_date", form.work_date.data, entity) or form.work_date.data,
        master_id=_uuid_or_none(master_raw),
        comment=fp(u, m, "comment", form.comment.data, entity),
        member_ids=[x for x in (_uuid_or_none(v) for v in members_raw) if x],
    )


@waybills_bp.route("/")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def index():
    filter_form = WaybillFilterForm(request.args)
    return render_template("waybills/index.html", filter_form=filter_form)


@waybills_bp.route("/table")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def table():
    filters = WaybillFilter(
        q=request.args.get("q", ""),
        status=request.args.get("status", ""),
        sort_by=request.args.get("sort_by", "work_date"),
        sort_dir=request.args.get("sort_dir", "desc"),
    )
    pagination = WaybillRepository.paginated_list(
        filters,
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 20, type=int),
    )
    return jsonify(
        {
            "table_html": render_template("waybills/partials/table.html", pagination=pagination, status_label=status_label, row_status_class=row_status_class),
            "pagination_html": render_template("waybills/partials/pagination.html", pagination=pagination),
        }
    )


@waybills_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_WAYBILLS_CREATE)
def create():
    form = WaybillForm()
    _prepare_form(form)
    if request.method == "GET":
        form.number.data = WaybillRepository.next_number()
        form.work_date.data = date.today()
        if current_user.has_permission("waybills.create"):
            form.master_id.data = str(current_user.id)
    if form.validate_on_submit():
        try:
            item = WaybillService.create(_payload(form), current_user.id)
            flash("Путевой лист создан.", "success")
            return redirect(url_for("waybills.detail", waybill_id=item.id))
        except ValidationError as exc:
            flash(str(exc), "danger")
    if is_ajax():
        return render_template("waybills/partials/form_modal.html", form=form, form_action=url_for("waybills.create"), mode="create")
    return render_template("waybills/form.html", form=form, mode="create")


@waybills_bp.route("/<uuid:waybill_id>")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def detail(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        flash("Путевой лист не найден.", "danger")
        return redirect(url_for("waybills.index"))
    stops = [s for s in item.stops if s.deleted_at is None]
    stops.sort(key=lambda s: s.sort_order)
    nearby_hits = []
    nearby_text = ""
    if stops:
        nearby_hits, nearby_text = WaybillService.nearby_for_stop(item, stops[0])
    status_form = WaybillStatusForm()
    status_form.status.choices = [(code, name) for code, name in WAYBILL_STATUSES if can_transition(item.status, code)]
    open_requests = list(db.session.scalars(db.select(Request).where(Request.active_filter()).order_by(Request.created_at.desc()).limit(40)))
    open_defects = list(db.session.scalars(db.select(Defect).where(Defect.active_filter()).order_by(Defect.created_at.desc()).limit(40)))
    return render_template(
        "waybills/detail.html",
        item=item,
        stops=stops,
        nearby_hits=nearby_hits,
        nearby_text=nearby_text,
        status_form=status_form,
        stop_form=WaybillStopForm(),
        status_label=status_label(item.status),
        open_requests=open_requests,
        open_defects=open_defects,
        members=[m for m in item.members if m.deleted_at is None],
    )


@waybills_bp.route("/<uuid:waybill_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def edit(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        flash("Путевой лист не найден.", "danger")
        return redirect(url_for("waybills.index"))
    form = WaybillForm(obj=item)
    _prepare_form(form)
    if request.method == "GET":
        form.master_id.data = str(item.master_id)
        form.member_ids.data = [str(m.user_id) for m in item.members if m.deleted_at is None]
    if form.validate_on_submit():
        try:
            WaybillService.update(item, _payload(form, item), current_user.id)
            flash("Путевой лист обновлён.", "success")
            return redirect(url_for("waybills.detail", waybill_id=item.id))
        except ValidationError as exc:
            flash(str(exc), "danger")
    return render_template("waybills/form.html", form=form, mode="edit", item=item)


@waybills_bp.route("/<uuid:waybill_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_DELETE)
def delete(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        flash("Путевой лист не найден.", "danger")
        return redirect(url_for("waybills.index"))
    WaybillService.delete(item, current_user.id)
    flash("Путевой лист удалён.", "success")
    return redirect(url_for("waybills.index"))


@waybills_bp.route("/<uuid:waybill_id>/status", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_STATUS_CHANGE)
def change_status(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        return redirect(url_for("waybills.index"))
    form = WaybillStatusForm()
    form.status.choices = [(code, name) for code, name in WAYBILL_STATUSES]
    if form.validate_on_submit():
        try:
            WaybillService.change_status(item, form.status.data, current_user.id)
            flash("Статус обновлён.", "success")
        except ValidationError as exc:
            flash(str(exc), "danger")
    return redirect(url_for("waybills.detail", waybill_id=item.id))


@waybills_bp.route("/<uuid:waybill_id>/stops", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def add_stop(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        return redirect(url_for("waybills.index"))
    entity_type = request.form.get("entity_type") or ""
    entity_id = _uuid_or_none(request.form.get("entity_id"))
    if entity_id is None:
        flash("Выберите заявку или дефект.", "danger")
        return redirect(url_for("waybills.detail", waybill_id=item.id))
    try:
        WaybillService.add_stop(item, entity_type=entity_type, entity_id=entity_id, user_id=current_user.id, comment=request.form.get("comment"))
        flash("Точка добавлена.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("waybills.detail", waybill_id=item.id))


@waybills_bp.route("/<uuid:waybill_id>/stops/<uuid:stop_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def remove_stop(waybill_id: uuid.UUID, stop_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        return redirect(url_for("waybills.index"))
    try:
        WaybillService.remove_stop(item, stop_id, current_user.id)
        flash("Точка удалена.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("waybills.detail", waybill_id=item.id))


@waybills_bp.route("/<uuid:waybill_id>/stops/reorder", methods=["POST"])
@login_required
@permission_required(PERM_WAYBILLS_EDIT)
def reorder(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        return jsonify({"ok": False}), 404
    raw = request.get_json(silent=True) or request.form
    ids = raw.get("stop_ids") or raw.getlist("stop_ids[]") or raw.getlist("stop_ids")
    parsed = [_uuid_or_none(v) for v in ids]
    if any(v is None for v in parsed):
        return jsonify({"ok": False, "message": "Некорректный список"}), 400
    try:
        WaybillService.reorder_stops(item, parsed, current_user.id)
        return jsonify({"ok": True})
    except ValidationError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400


@waybills_bp.route("/<uuid:waybill_id>/nearby")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def nearby(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        return jsonify({"hits": [], "summary": ""}), 404
    stop_id = _uuid_or_none(request.args.get("stop_id"))
    stops = [s for s in item.stops if s.deleted_at is None]
    stop = next((s for s in stops if s.id == stop_id), stops[0] if stops else None)
    if stop is None:
        return jsonify({"hits": [], "summary": ""})
    hits, summary = WaybillService.nearby_for_stop(item, stop)
    return jsonify(
        {
            "summary": summary,
            "hits": [
                {
                    "entity_type": h.entity_type,
                    "entity_id": str(h.entity_id),
                    "number": h.number,
                    "address": h.address,
                    "priority": h.priority,
                    "url": h.url,
                }
                for h in hits
            ],
        }
    )


@waybills_bp.route("/<uuid:waybill_id>/map.json")
@login_required
@permission_required(PERM_WAYBILLS_VIEW)
def map_json(waybill_id: uuid.UUID):
    item = WaybillRepository.get_by_id(waybill_id)
    if item is None:
        return jsonify({"points": []}), 404
    points = []
    for stop in sorted((s for s in item.stops if s.deleted_at is None), key=lambda s: s.sort_order):
        if stop.latitude is None or stop.longitude is None:
            continue
        points.append(
            {
                "id": str(stop.id),
                "order": stop.sort_order,
                "address": stop.address,
                "lat": float(stop.latitude),
                "lng": float(stop.longitude),
                "type": "request" if stop.request_id else "defect",
                "number": stop.request.number if stop.request else (stop.defect.number if stop.defect else ""),
            }
        )
    return jsonify({"points": points, "remaining": 0})
