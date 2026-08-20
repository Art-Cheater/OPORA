"""Blueprint модуля импорта ЕИС."""

from flask import Blueprint

eis_bp = Blueprint(
    "eis",
    __name__,
    url_prefix="/eis",
    template_folder="templates",
)

from app.modules.eis import routes  # noqa: E402, F401
