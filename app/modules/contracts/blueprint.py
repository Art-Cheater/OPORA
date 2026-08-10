"""Blueprint модуля контрактов."""

from flask import Blueprint

contracts_bp = Blueprint(
    "contracts",
    __name__,
    url_prefix="/contracts",
    template_folder="templates",
)

from app.modules.contracts import routes  # noqa: E402, F401
