"""Маршруты журнала действий."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import Response, jsonify, render_template, request
from flask_login import current_user, login_required

from app.core.audit_service import AuditService
from app.core.decorators import permission_required
from app.models.auth.constants import PERM_AUDIT_EXPORT, PERM_AUDIT_VIEW
from app.modules.audit.blueprint import audit_bp
from app.modules.audit.forms import AuditFilterForm
from app.modules.audit.repositories import AuditFilter, AuditRepository


def _filters_from_request() -> AuditFilter:
    return AuditFilter(
        q=request.args.get("q", ""),
        user_id=request.args.get("user_id", ""),
        action=request.args.get("action", ""),
        entity_type=request.args.get("entity_type", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
    )


def _prepare_filter_form(form: AuditFilterForm) -> None:
    users = AuditRepository.get_users_for_filter()
    form.user_id.choices = [("", "Все пользователи")] + [
        (str(u.id), u.full_name) for u in users
    ]


@audit_bp.route("/")
@login_required
@permission_required(PERM_AUDIT_VIEW)
def index():
    filter_form = AuditFilterForm(request.args)
    _prepare_filter_form(filter_form)
    return render_template(
        "audit/index.html",
        filter_form=filter_form,
        can_export=current_user.has_permission(PERM_AUDIT_EXPORT),
    )


@audit_bp.route("/table")
@login_required
@permission_required(PERM_AUDIT_VIEW)
def table():
    filters = _filters_from_request()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 30, type=int)
    pagination = AuditRepository.paginated_list(filters, page=page, per_page=per_page)
    html = render_template("audit/partials/table.html", audit_pagination=pagination)
    pager = render_template("audit/partials/pagination.html", audit_pagination=pagination)
    return jsonify({"table_html": html, "pagination_html": pager})


@audit_bp.route("/export")
@login_required
@permission_required(PERM_AUDIT_EXPORT)
def export():
    filters = _filters_from_request()
    rows = AuditRepository.export_list(filters)

    AuditService.log(
        user_id=current_user.id,
        action="export",
        entity_type="audit",
        description=f"Экспорт журнала действий ({len(rows)} записей)",
        commit=True,
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        ["Время", "Пользователь", "IP", "Действие", "Объект", "ID объекта", "Описание"]
    )
    for entry in rows:
        writer.writerow(
            [
                entry.created_at.strftime("%d.%m.%Y %H:%M:%S") if entry.created_at else "",
                entry.user.full_name if entry.user else "—",
                entry.ip_address or "",
                AuditService.action_label(entry.action),
                AuditService.entity_label(entry.entity_type),
                str(entry.entity_id) if entry.entity_id else "",
                entry.description or "",
            ]
        )

    filename = f"audit_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
