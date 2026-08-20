"""Blueprint модуля договоров на опорах."""

from flask import Blueprint

agreements_bp = Blueprint(
    "agreements",
    __name__,
    url_prefix="/agreements",
    template_folder="templates",
)

from app.modules.agreements import routes  # noqa: E402, F401
