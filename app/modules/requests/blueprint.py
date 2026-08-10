"""Blueprint модуля заявок."""

from flask import Blueprint

requests_bp = Blueprint(
    "requests",
    __name__,
    url_prefix="/requests",
    template_folder="templates",
)

from app.modules.requests import routes  # noqa: E402, F401
