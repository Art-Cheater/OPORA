"""Blueprint публичной карты заявок."""

from flask import Blueprint

public_site_bp = Blueprint("public_site", __name__, url_prefix="/public/kirovsvet")

from app.modules.public_site import routes  # noqa: E402, F401
