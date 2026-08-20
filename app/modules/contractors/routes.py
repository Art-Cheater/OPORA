"""Маршруты справочника подрядчиков."""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import ValidationError
from app.core.forms_utils import form_errors_message
from app.models.auth.constants import (
    PERM_CONTRACTORS_CREATE,
    PERM_CONTRACTORS_DELETE,
    PERM_CONTRACTORS_EDIT,
    PERM_CONTRACTORS_VIEW,
)
from app.models.enums import ProjectStatus
from app.modules.contractors.blueprint import contractors_bp
from app.modules.contractors.forms import ContractorFilterForm, ContractorForm
from app.modules.contractors.repositories import ContractorFilter, ContractorRepository
from app.modules.contractors.services import ContractorPayload, ContractorService


def _payload_from_form(form: ContractorForm) -> ContractorPayload:
    return ContractorPayload(
        name=form.name.data or "",
        inn=form.inn.data,
        kpp=form.kpp.data,
        kpp_largest=form.kpp_largest.data,
        address=form.address.data,
        phone=form.phone.data,
        email=form.email.data,
        notes=form.notes.data,
    )


@contractors_bp.route("/")
@login_required
@permission_required(PERM_CONTRACTORS_VIEW)
def index():
    filter_form = ContractorFilterForm(request.args)
    filters = ContractorFilter(
        q=request.args.get("q", ""),
        sort_by=request.args.get("sort_by", "name"),
        sort_dir=request.args.get("sort_dir", "asc"),
    )
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    pagination = ContractorRepository.paginated_list(filters, page=page, per_page=per_page)
    return render_template(
        "contractors/index.html",
        filter_form=filter_form,
        pagination=pagination,
        filters=filters,
    )


@contractors_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(PERM_CONTRACTORS_CREATE)
def create():
    form = ContractorForm()
    if form.validate_on_submit():
        try:
            contractor = ContractorService.create(_payload_from_form(form), current_user.id)
        except ValidationError as exc:
            flash(str(exc), "danger")
        else:
            flash("Подрядчик создан.", "success")
            return redirect(url_for("contractors.detail", contractor_id=contractor.id))
    elif request.method == "POST":
        flash(form_errors_message(form), "danger")
    return render_template("contractors/form.html", form=form, contractor=None)


@contractors_bp.route("/<uuid:contractor_id>")
@login_required
@permission_required(PERM_CONTRACTORS_VIEW)
def detail(contractor_id):
    contractor = ContractorRepository.get_by_id(contractor_id)
    if contractor is None:
        abort(404)
    contracts = [
        link.contract
        for link in contractor.contract_links
        if link.deleted_at is None and link.contract is not None and link.contract.deleted_at is None
    ]
    contracts.sort(key=lambda item: item.contract_date or item.created_at, reverse=True)
    projects = []
    objects = []
    tenders = []
    seen_p: set = set()
    seen_o: set = set()
    seen_t: set = set()
    for contract in contracts:
        if contract.project and contract.project.id not in seen_p:
            seen_p.add(contract.project.id)
            projects.append(contract.project)
        if contract.tender_application and contract.tender_application.id not in seen_t:
            seen_t.add(contract.tender_application.id)
            tenders.append(contract.tender_application)
        for obj in contract.work_objects:
            if obj.id not in seen_o:
                seen_o.add(obj.id)
                objects.append(obj)
    return render_template(
        "contractors/detail.html",
        contractor=contractor,
        contracts=contracts,
        projects=projects,
        objects=objects,
        tenders=tenders,
        project_status=ProjectStatus,
    )


@contractors_bp.route("/<uuid:contractor_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required(PERM_CONTRACTORS_EDIT)
def edit(contractor_id):
    contractor = ContractorRepository.get_by_id(contractor_id)
    if contractor is None:
        abort(404)
    form = ContractorForm(obj=contractor)
    if form.validate_on_submit():
        try:
            ContractorService.update(contractor, _payload_from_form(form), current_user.id)
        except ValidationError as exc:
            flash(str(exc), "danger")
        else:
            flash("Подрядчик обновлён.", "success")
            return redirect(url_for("contractors.detail", contractor_id=contractor.id))
    elif request.method == "POST":
        flash(form_errors_message(form), "danger")
    return render_template("contractors/form.html", form=form, contractor=contractor)


@contractors_bp.route("/<uuid:contractor_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_CONTRACTORS_DELETE)
def delete(contractor_id):
    contractor = ContractorRepository.get_by_id(contractor_id)
    if contractor is None:
        abort(404)
    ContractorService.soft_delete(contractor, current_user.id)
    flash("Подрядчик удалён.", "success")
    return redirect(url_for("contractors.index"))
