"""Blueprint глобального поиска."""

from flask import Blueprint

search_bp = Blueprint(
    "search",
    __name__,
    url_prefix="/search",
    template_folder="templates",
)

from app.modules.search import routes  # noqa: E402, F401
