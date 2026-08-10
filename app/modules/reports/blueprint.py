"""Blueprint модуля отчётов."""

from flask import Blueprint

reports_bp = Blueprint(
    "reports",
    __name__,
    url_prefix="/reports",
    template_folder="templates",
)

from app.modules.reports import routes  # noqa: E402, F401
