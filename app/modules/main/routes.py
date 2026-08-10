"""Маршруты главного модуля."""

from flask import render_template
from flask_login import current_user, login_required

from app.modules.main.blueprint import main_bp


@main_bp.route("/")
@login_required
def index():
    """Главная страница — дашборд."""
    return render_template(
        "main/index.html",
        user=current_user,
    )


@main_bp.route("/about")
def about():
    """Информация о системе."""
    return render_template("main/about.html")
