"""Blueprint путевых листов."""

from flask import Blueprint

waybills_bp = Blueprint(
    "waybills",
    __name__,
    url_prefix="/waybills",
    template_folder="templates",
)

from app.modules.waybills import routes  # noqa: E402, F401
