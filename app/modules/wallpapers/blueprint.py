"""Blueprint модуля обоев."""

from flask import Blueprint

wallpapers_bp = Blueprint(
    "wallpapers",
    __name__,
    url_prefix="/wallpapers",
    template_folder="templates",
)

from app.modules.wallpapers import routes  # noqa: E402, F401
