"""Маршруты главного модуля."""

from flask import current_app, render_template
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


@main_bp.route("/health")
def health():
    """Лёгкая проверка живости (без логина и тяжёлых запросов)."""
    return (
        {
            "status": "ok",
            "release": "20260821g",
            "eis_year_from": int(current_app.config.get("EIS_YEAR_FROM") or 0),
        },
        200,
        {"Cache-Control": "no-store"},
    )


@main_bp.route("/about")
def about():
    """Информация о системе."""
    return render_template("main/about.html")
