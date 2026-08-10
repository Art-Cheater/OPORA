"""Blueprint модуля ролей."""

from flask import Blueprint

roles_bp = Blueprint(
    "roles",
    __name__,
    url_prefix="/roles",
    template_folder="templates",
)

from app.modules.roles import routes  # noqa: E402, F401
