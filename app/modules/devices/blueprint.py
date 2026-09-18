from flask import Blueprint

devices_bp = Blueprint("devices", __name__, url_prefix="/devices", template_folder="templates")

from app.modules.devices import routes  # noqa: E402,F401
