"""Blueprint модуля заявок на торги."""

from flask import Blueprint

tenders_bp = Blueprint(
    "tenders",
    __name__,
    url_prefix="/tenders",
    template_folder="templates",
)

from app.modules.tenders import routes  # noqa: E402, F401
