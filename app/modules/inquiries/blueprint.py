"""Blueprint модуля обращений."""

from flask import Blueprint

inquiries_bp = Blueprint(
    "inquiries",
    __name__,
    url_prefix="/inquiries",
    template_folder="templates",
)

from app.modules.inquiries import routes  # noqa: E402, F401
