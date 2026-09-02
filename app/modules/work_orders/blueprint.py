"""Blueprint рабочего места мастера."""

from flask import Blueprint

work_orders_bp = Blueprint(
    "work_orders",
    __name__,
    url_prefix="/work-orders",
    template_folder="templates",
)

from app.modules.work_orders import routes  # noqa: E402, F401
