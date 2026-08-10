"""Blueprint журнала действий."""

from flask import Blueprint

audit_bp = Blueprint(
    "audit",
    __name__,
    url_prefix="/audit",
    template_folder="templates",
)

from app.modules.audit import routes  # noqa: E402, F401
