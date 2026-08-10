"""Маршруты модуля _template."""

from flask import render_template
from flask_login import login_required

from app.modules._template.blueprint import template_bp


@template_bp.route("/")
@login_required
def index():
    """Главная страница модуля."""
    return render_template("_template/index.html")
