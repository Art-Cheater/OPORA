from flask import Blueprint

irz_bp = Blueprint("irz", __name__, url_prefix="/irz", template_folder="templates")

from app.modules.irz import routes  # noqa: E402,F401
