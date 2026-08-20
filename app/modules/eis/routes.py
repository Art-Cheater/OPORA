"""Окно импорта ЕИС: история, ошибки, ручной запуск."""

from __future__ import annotations

import threading

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.extensions import db
from app.models.auth.constants import PERM_EIS_RUN, PERM_EIS_VIEW
from app.models.eis.eis_import_event import EisImportEvent
from app.models.eis.eis_import_run import EisImportRun
from app.modules.eis.blueprint import eis_bp
from app.modules.eis.services import EisImportService, EisSyncLocked


def _latest_run() -> EisImportRun | None:
    return db.session.scalar(
        db.select(EisImportRun)
        .where(EisImportRun.active_filter())
        .order_by(EisImportRun.started_at.desc())
        .limit(1)
    )


@eis_bp.route("/")
@login_required
@permission_required(PERM_EIS_VIEW)
def index():
    page = request.args.get("page", 1, type=int)
    runs = db.paginate(
        db.select(EisImportRun)
        .where(EisImportRun.active_filter())
        .order_by(EisImportRun.started_at.desc()),
        page=page,
        per_page=15,
        error_out=False,
    )
    latest = _latest_run()
    unmatched = []
    if latest is not None:
        unmatched = list(
            db.session.scalars(
                db.select(EisImportEvent)
                .where(
                    EisImportEvent.run_id == latest.id,
                    EisImportEvent.kind.in_(("unmatched", "error")),
                )
                .order_by(EisImportEvent.created_at.desc())
                .limit(20)
            )
        )
    running = EisImportService().is_running()
    return render_template(
        "eis/index.html",
        runs=runs,
        latest=latest,
        unmatched=unmatched,
        running=running,
    )


@eis_bp.route("/runs/<uuid:run_id>")
@login_required
@permission_required(PERM_EIS_VIEW)
def run_detail(run_id):
    run = db.session.get(EisImportRun, run_id)
    if run is None or run.deleted_at is not None:
        flash("Прогон не найден.", "danger")
        return redirect(url_for("eis.index"))
    kind = request.args.get("kind", "")
    stmt = db.select(EisImportEvent).where(EisImportEvent.run_id == run.id)
    if kind:
        stmt = stmt.where(EisImportEvent.kind == kind)
    stmt = stmt.order_by(EisImportEvent.created_at.desc())
    events = db.paginate(stmt, page=request.args.get("page", 1, type=int), per_page=50, error_out=False)
    return render_template("eis/run_detail.html", run=run, events=events, kind=kind)


@eis_bp.route("/run", methods=["POST"])
@login_required
@permission_required(PERM_EIS_RUN)
def run_now():
    service = EisImportService()
    if service.is_running() is not None:
        flash("Импорт уже выполняется. Дождитесь окончания.", "warning")
        return redirect(url_for("eis.index"))
    app = current_app._get_current_object()
    user_id = current_user.id

    def worker():
        with app.app_context():
            try:
                EisImportService().sync(trigger="manual", user_id=user_id)
            except EisSyncLocked:
                return
            except Exception:
                db.session.rollback()

    threading.Thread(target=worker, daemon=True, name="eis-sync").start()
    flash("Импорт ЕИС запущен. Обновите страницу через несколько минут.", "success")
    return redirect(url_for("eis.index"))
