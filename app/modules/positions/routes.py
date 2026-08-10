"""Маршруты справочника должностей."""

from flask import render_template
from flask_login import login_required

from app.core.decorators import permission_required
from app.models.auth.constants import PERM_ROLES_MANAGE
from app.modules.positions.blueprint import positions_bp
from app.modules.positions.repositories import PositionRepository


@positions_bp.route("/")
@login_required
@permission_required(PERM_ROLES_MANAGE)
def index():
    positions = PositionRepository.list_active()
    return render_template("positions/index.html", positions=positions)
