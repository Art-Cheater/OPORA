"""Маршруты раздела отчётов."""

from __future__ import annotations

import csv
import io
from datetime import date

from flask import Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.audit_service import AuditService
from app.core.decorators import permission_required
from app.models.auth.constants import PERM_REPORTS_EXPORT, PERM_REPORTS_VIEW
from app.modules.reports.blueprint import reports_bp
from app.modules.reports.forms import RequestsReportForm
from app.modules.reports.services import ReportsService, resolve_period


@reports_bp.route("/")
@login_required
@permission_required(PERM_REPORTS_VIEW)
def index():
    return redirect(url_for("reports.requests"))


def _period_from_request(form: RequestsReportForm):
    period_key = form.period.data or request.args.get("period", "week") or "week"
    date_from = form.date_from.data
    date_to = form.date_to.data
    if isinstance(date_from, str):
        try:
            date_from = date.fromisoformat(date_from)
        except ValueError:
            date_from = None
    if isinstance(date_to, str):
        try:
            date_to = date.fromisoformat(date_to)
        except ValueError:
            date_to = None

    if period_key == "custom" and (not date_from or not date_to):
        flash("Для своего периода укажите даты «С» и «По».", "warning")
        period_key = "week"

    period = resolve_period(period_key, date_from, date_to)
    form.period.data = period.key
    form.date_from.data = period.date_from
    form.date_to.data = period.date_to
    return period


@reports_bp.route("/requests")
@login_required
@permission_required(PERM_REPORTS_VIEW)
def requests():
    form = RequestsReportForm(request.args, meta={"csrf": False})
    period = _period_from_request(form)
    report = ReportsService.requests_report(period)
    return render_template(
        "reports/requests.html",
        form=form,
        report=report,
        can_export=current_user.has_permission(PERM_REPORTS_EXPORT),
    )


@reports_bp.route("/requests/export")
@login_required
@permission_required(PERM_REPORTS_EXPORT)
def requests_export():
    form = RequestsReportForm(request.args, meta={"csrf": False})
    period = _period_from_request(form)
    report = ReportsService.requests_report(period)
    rows = ReportsService.requests_report_csv_rows(report)

    AuditService.log(
        user_id=current_user.id,
        action="export",
        entity_type="reports",
        description=f"Экспорт отчёта по заявкам ({period.label})",
        commit=True,
    )

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerows(rows)
    payload = "\ufeff" + buf.getvalue()
    filename = f"requests_report_{period.date_from}_{period.date_to}.csv"
    return Response(
        payload,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
