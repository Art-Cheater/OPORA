"""Blueprint модуля подрядчиков."""

from flask import Blueprint

contractors_bp = Blueprint(
    "contractors",
    __name__,
    url_prefix="/contractors",
    template_folder="templates",
)

from app.modules.contractors import routes  # noqa: E402, F401
