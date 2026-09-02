"""Blueprint модуля дефектов."""

from flask import Blueprint

defects_bp = Blueprint(
    "defects",
    __name__,
    url_prefix="/defects",
    template_folder="templates",
)

from app.modules.defects import routes  # noqa: E402, F401
