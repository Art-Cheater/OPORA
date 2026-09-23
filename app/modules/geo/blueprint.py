"""Blueprint единого географического API."""

from flask import Blueprint

geo_bp = Blueprint("geo", __name__, url_prefix="/api")

from app.modules.geo import routes  # noqa: E402, F401
