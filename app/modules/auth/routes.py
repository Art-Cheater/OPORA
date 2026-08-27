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


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    """Выход из системы. POST предпочтителен (CSRF); GET оставлен для совместимости закладок."""
    if request.method == "GET":
        # Не выполняем logout по cross-site GET (SameSite=Lax всё ещё шлёт cookie на top-level).
        return render_template("auth/logout_confirm.html")
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


@auth_bp.route("/ui/appearance", methods=["POST"])
@login_required
def ui_appearance():
    """Сохранение темы / выбранного системного фона (JSON)."""
    from flask import jsonify

    from app.modules.auth.appearance_service import AppearanceService

    data = request.get_json(silent=True) or {}
    try:
        if "theme" in data:
            AppearanceService.set_theme(current_user, data.get("theme"))
        if "background" in data:
            AppearanceService.set_background(current_user, data.get("background") or "none")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(
        {
            "ok": True,
            "theme": current_user.ui_theme,
            "background": current_user.ui_background,
        }
    )


@auth_bp.route("/ui/background", methods=["POST"])
@login_required
def ui_background_upload():
    """Загрузка пользовательского фона."""
    from flask import jsonify

    from app.core.upload_utils import UploadValidationError
    from app.core.ui_backgrounds import resolve_user_background_url
    from app.modules.auth.appearance_service import AppearanceService

    file_storage = request.files.get("background") or request.files.get("file")
    try:
        AppearanceService.upload_background(current_user, file_storage)
    except UploadValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(
        {
            "ok": True,
            "background": "custom",
            "url": resolve_user_background_url(current_user),
        }
    )


@auth_bp.route("/ui/background", methods=["DELETE"])
@login_required
def ui_background_delete():
    """Удаление пользовательского фона."""
    from flask import jsonify

    from app.modules.auth.appearance_service import AppearanceService

    AppearanceService.clear_custom_background(current_user)
    return jsonify({"ok": True, "background": current_user.ui_background})


@auth_bp.route("/ui/background/file")
@login_required
def ui_background_file():
    """Отдаёт только свой загруженный фон текущего пользователя."""
    from flask import abort, send_file

    from app.core.upload_utils import resolve_storage_path

    key = current_user.ui_background_key
    if not key or current_user.ui_background != "custom":
        abort(404)
    # чужой ключ в сессии невозможен — ключ берётся из своей записи
    try:
        path = resolve_storage_path(key)
    except FileNotFoundError:
        abort(404)
    if not path.is_file():
        abort(404)
    # защита: ключ обязан принадлежать каталогу пользователя
    expected_prefix = f"users/{current_user.id}/background/"
    if not str(key).replace("\\", "/").startswith(expected_prefix):
        abort(403)
    return send_file(path, conditional=True, max_age=3600)


@auth_bp.route("/login-logs")
@login_required
@permission_required(PERM_AUTH_LOGIN_LOGS_VIEW)
def login_logs():
    """Журнал входов (для администраторов и директоров)."""
    logs = LoginLogService.get_all_logs(limit=200)
    return render_template("auth/login_logs.html", login_logs=logs)
