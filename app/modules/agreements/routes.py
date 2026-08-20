"""Маршруты договоров на опорах."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.forms_utils import form_errors_message
from app.core.upload_utils import UploadValidationError
from app.extensions import db
from app.models.auth.constants import (
    PERM_AGREEMENTS_CREATE,
    PERM_AGREEMENTS_DELETE,
    PERM_AGREEMENTS_VIEW,
)
from app.models.base import utcnow
from app.modules.agreements.blueprint import agreements_bp
from app.modules.agreements.forms import AgreementFilterForm, AgreementUploadForm
from app.modules.agreements.repositories import AgreementFilter, AgreementRepository
from app.modules.agreements.services import AgreementService


@agreements_bp.route("/")
@login_required
@permission_required(PERM_AGREEMENTS_VIEW)
def index():
    filter_form = AgreementFilterForm(request.args)
    q = request.args.get("q", "")
    hits = AgreementService.search_address(q) if q.strip() else []
    return render_template(
        "agreements/index.html",
        filter_form=filter_form,
        hits=hits,
        q=q,
        upload_form=AgreementUploadForm(),
    )


@agreements_bp.route("/table")
@login_required
@permission_required(PERM_AGREEMENTS_VIEW)
def table():
    q = request.args.get("q", "")
    pagination = AgreementRepository.paginated_list(
        AgreementFilter(q=q),
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 20, type=int),
    )
    return jsonify(
        {
            "table_html": render_template("agreements/partials/table.html", pagination=pagination),
            "pagination_html": render_template(
                "agreements/partials/pagination.html", pagination=pagination
            ),
        }
    )


@agreements_bp.route("/upload", methods=["POST"])
@login_required
@permission_required(PERM_AGREEMENTS_CREATE)
def upload():
    form = AgreementUploadForm()
    if not form.validate_on_submit():
        flash(form_errors_message(form), "danger")
        return redirect(url_for("agreements.index"))
    try:
        outcome = AgreementService.import_docx(form.file.data, current_user.id)
    except (ValidationError, UploadValidationError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("agreements.index"))
    agreement = outcome.agreement
    verb = "Загружен" if outcome.created else "Обновлён"
    extra = f", адресов: {len(agreement.sites)}"
    if agreement.parse_warning:
        extra += f". {agreement.parse_warning}"
    flash(f"{verb} {agreement.title}{extra}.", "success")
    return redirect(url_for("agreements.detail", agreement_id=agreement.id))


@agreements_bp.route("/map.json")
@login_required
@permission_required(PERM_AGREEMENTS_VIEW)
def map_data():
    agreement_id = request.args.get("agreement_id", type=uuid.UUID)
    AgreementService.ensure_background_geocode()
    points, remaining = AgreementService.map_points(agreement_id=agreement_id)
    return jsonify(
        {
            "center": [58.6035, 49.668],
            "remaining": remaining,
            "points": [
                {
                    "id": str(item.site_id),
                    "lat": item.lat,
                    "lng": item.lng,
                    "address": item.address,
                    "customer": item.customer_name or "—",
                    "title": item.title,
                    "number": item.number or "",
                    "subject": item.subject or "",
                    "period": item.period,
                    "mounts": item.mounts_count,
                    "poles": item.poles_count,
                    "note": item.note or "",
                    "url": url_for("agreements.detail", agreement_id=item.agreement_id),
                    "file_url": (
                        url_for("agreements.download", agreement_id=item.agreement_id)
                        if item.has_file
                        else ""
                    ),
                }
                for item in points
            ],
        }
    )


@agreements_bp.route("/<uuid:agreement_id>")
@login_required
@permission_required(PERM_AGREEMENTS_VIEW)
def detail(agreement_id):
    agreement = AgreementRepository.get_by_id(agreement_id)
    if agreement is None:
        abort(404)
    return render_template("agreements/detail.html", agreement=agreement)


@agreements_bp.route("/<uuid:agreement_id>/file")
@login_required
@permission_required(PERM_AGREEMENTS_VIEW)
def download(agreement_id):
    agreement = AgreementRepository.get_by_id(agreement_id)
    if agreement is None or not agreement.storage_key:
        abort(404)
    path = Path(current_app.config["UPLOAD_FOLDER"]) / agreement.storage_key
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=agreement.source_filename or path.name,
    )


@agreements_bp.route("/<uuid:agreement_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_AGREEMENTS_DELETE)
def delete(agreement_id):
    agreement = AgreementRepository.get_by_id(agreement_id)
    if agreement is None:
        abort(404)
    agreement.deleted_at = utcnow()
    agreement.updated_by = current_user.id
    db.session.commit()
    flash("Договор скрыт.", "info")
    return redirect(url_for("agreements.index"))
