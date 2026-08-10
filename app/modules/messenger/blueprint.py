"""Blueprint корпоративного мессенджера."""

from flask import Blueprint

messenger_bp = Blueprint(
    "messenger",
    __name__,
    url_prefix="/messenger",
    template_folder="templates",
)

from app.modules.messenger import routes  # noqa: E402, F401
