"""Blueprint модуля _template — замените _template на имя модуля."""

from flask import Blueprint

# Замените _template на имя модуля
template_bp = Blueprint(
    "_template",
    __name__,
    url_prefix="/_template",
    template_folder="templates",
)

from app.modules._template import routes  # noqa: E402, F401
