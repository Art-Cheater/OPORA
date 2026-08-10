"""Маршруты модуля auth."""

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import AuthenticationError
from app.extensions import db
from app.models.auth.constants import PERM_AUTH_LOGIN_LOGS_VIEW, PERM_PROFILE_EDIT
from app.modules.auth.blueprint import auth_bp
from app.modules.auth.forms import ChangePasswordForm, LoginForm, ProfileForm
from app.modules.auth.login_log_service import LoginLogService
from app.modules.auth.services import AuthService


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Страница входа в систему."""
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        try:
            AuthService.authenticate(
                email=form.email.data,
                password=form.password.data,
                remember=form.remember.data,
            )
            flash("Вход кайф!", "success")
            next_page = request.args.get("next")
            # Только относительные URL (защита от open redirect)
            if next_page and next_page.startswith("/") and not next_page.startswith("//"):
                return redirect(next_page)
            return redirect(url_for("main.index"))
        except AuthenticationError as exc:
            flash(exc.message, "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    """Выход из системы."""
    AuthService.logout()
    flash("Вы успешно вышли из системы.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Страница профиля пользователя."""
    profile_form = ProfileForm(obj=current_user)
    password_form = ChangePasswordForm()
    login_logs = LoginLogService.get_user_logs(current_user.id, limit=15)

    if request.method == "POST" and profile_form.validate_on_submit():
        if not current_user.has_permission(PERM_PROFILE_EDIT):
            flash("Недостаточно прав для редактирования профиля.", "danger")
        else:
            current_user.full_name = profile_form.full_name.data.strip()
            current_user.phone = profile_form.phone.data.strip() or None
            current_user.position = profile_form.position.data.strip() or None
            current_user.department = profile_form.department.data.strip() or None
            current_user.updated_by = current_user.id
            db.session.commit()
            flash("Профиль успешно обновлён.", "success")
            return redirect(url_for("auth.profile"))

    return render_template(
        "auth/profile.html",
        profile_form=profile_form,
        password_form=password_form,
        login_logs=login_logs,
    )


@auth_bp.route("/profile/change-password", methods=["POST"])
@login_required
def change_password():
    """Смена пароля текущего пользователя."""
    form = ChangePasswordForm()
    if not form.validate_on_submit():
        for field_errors in form.errors.values():
            for error in field_errors:
                flash(error, "danger")
        return redirect(url_for("auth.profile"))

    try:
        AuthService.change_password(
            user=current_user,
            current_password=form.current_password.data,
            new_password=form.new_password.data,
        )
        flash("Пароль успешно изменён.", "success")
    except AuthenticationError as exc:
        flash(exc.message, "danger")

    return redirect(url_for("auth.profile"))


@auth_bp.route("/login-logs")
@login_required
@permission_required(PERM_AUTH_LOGIN_LOGS_VIEW)
def login_logs():
    """Журнал входов (для администраторов и директоров)."""
    logs = LoginLogService.get_all_logs(limit=200)
    return render_template("auth/login_logs.html", login_logs=logs)
