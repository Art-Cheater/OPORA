"""Blueprint модуля объектов."""

from flask import Blueprint

objects_bp = Blueprint(
    "objects",
    __name__,
    url_prefix="/objects",
    template_folder="templates",
)

from app.modules.objects import routes  # noqa: E402, F401
