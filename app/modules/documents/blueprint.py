"""Blueprint личных документов сотрудника."""

from flask import Blueprint

documents_bp = Blueprint(
    "documents",
    __name__,
    url_prefix="/documents",
    template_folder="templates",
)

from app.modules.documents import routes  # noqa: E402, F401
