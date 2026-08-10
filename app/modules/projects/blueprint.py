"""Blueprint модуля проектов."""

from flask import Blueprint

projects_bp = Blueprint(
    "projects",
    __name__,
    url_prefix="/projects",
    template_folder="templates",
)

from app.modules.projects import routes  # noqa: E402, F401
