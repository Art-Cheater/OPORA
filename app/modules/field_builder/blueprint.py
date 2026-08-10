"""Blueprint конструктора полей."""

from flask import Blueprint

field_builder_bp = Blueprint(
    "field_builder",
    __name__,
    url_prefix="/field-builder",
    template_folder="templates",
)

from app.modules.field_builder import routes  # noqa: E402, F401
