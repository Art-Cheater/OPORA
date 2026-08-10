"""Blueprint модуля должностей."""

from flask import Blueprint

positions_bp = Blueprint(
    "positions",
    __name__,
    url_prefix="/positions",
    template_folder="templates",
)

from app.modules.positions import routes  # noqa: E402, F401
