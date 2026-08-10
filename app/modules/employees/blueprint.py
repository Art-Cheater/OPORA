"""Blueprint модуля сотрудников."""

from flask import Blueprint

employees_bp = Blueprint(
    "employees",
    __name__,
    url_prefix="/employees",
    template_folder="templates",
)

from app.modules.employees import routes  # noqa: E402, F401
