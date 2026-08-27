"""Маршруты раздела «Обои»."""

from __future__ import annotations

import uuid

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import BooleanField, FileField, StringField, SubmitField
from wtforms.validators import DataRequired, Length

from app.core.decorators import permission_required
from app.core.upload_utils import UploadValidationError, resolve_storage_path
from app.extensions import db
from app.models.auth.constants import PERM_WALLPAPERS_MANAGE
from app.models.ui.wallpaper import Wallpaper
from app.modules.wallpapers.blueprint import wallpapers_bp
from app.modules.wallpapers.services import WallpaperService
from sqlalchemy import select


class WallpaperCreateForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=200)])
    image = FileField("Изображение", validators=[DataRequired()])
    submit = SubmitField("Добавить")


class WallpaperEditForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=200)])
    is_active = BooleanField("Доступно пользователям", default=True)
    submit = SubmitField("Сохранить")


@wallpapers_bp.route("/")
@login_required
@permission_required(PERM_WALLPAPERS_MANAGE)
def index():
    items = WallpaperService.list_all()
    form = WallpaperCreateForm()
    return render_template("wallpapers/index.html", items=items, form=form)


@wallpapers_bp.route("/create", methods=["POST"])
@login_required
@permission_required(PERM_WALLPAPERS_MANAGE)
def create():
    form = WallpaperCreateForm()
    if not form.validate_on_submit():
        for errs in form.errors.values():
            for err in errs:
                flash(err, "danger")
        return redirect(url_for("wallpapers.index"))
    try:
        WallpaperService.create(
            title=form.title.data,
            file_storage=form.image.data,
            user_id=current_user.id,
        )
        flash("Обои добавлены.", "success")
    except UploadValidationError as exc:
        flash(str(exc), "danger")
    except Exception:
        db.session.rollback()
        flash("Не удалось сохранить обои.", "danger")
    return redirect(url_for("wallpapers.index"))


@wallpapers_bp.route("/<uuid:wallpaper_id>/edit", methods=["POST"])
@login_required
@permission_required(PERM_WALLPAPERS_MANAGE)
def edit(wallpaper_id: uuid.UUID):
    item = _get_or_404(wallpaper_id)
    form = WallpaperEditForm()
    if not form.validate_on_submit():
        flash("Проверьте поля формы.", "danger")
        return redirect(url_for("wallpapers.index"))
    WallpaperService.update_meta(
        item,
        title=form.title.data,
        is_active=bool(form.is_active.data),
        user_id=current_user.id,
    )
    flash("Обои обновлены.", "success")
    return redirect(url_for("wallpapers.index"))


@wallpapers_bp.route("/<uuid:wallpaper_id>/delete", methods=["POST"])
@login_required
@permission_required(PERM_WALLPAPERS_MANAGE)
def delete(wallpaper_id: uuid.UUID):
    item = _get_or_404(wallpaper_id)
    WallpaperService.soft_delete(item, user_id=current_user.id)
    flash("Обои удалены.", "info")
    return redirect(url_for("wallpapers.index"))


@wallpapers_bp.route("/<uuid:wallpaper_id>/file")
@login_required
def file(wallpaper_id: uuid.UUID):
    """Отдача файла обоев любому авторизованному пользователю (для фона UI)."""
    item = db.session.execute(
        select(Wallpaper).where(
            Wallpaper.id == wallpaper_id,
            Wallpaper.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if item is None:
        abort(404)
    # Неактивные — только админу каталога (чтобы править превью)
    if not item.is_active and not current_user.has_permission(PERM_WALLPAPERS_MANAGE):
        abort(404)
    try:
        path = resolve_storage_path(item.storage_key)
    except FileNotFoundError:
        abort(404)
    if not path.is_file():
        abort(404)
    key = str(item.storage_key).replace("\\", "/")
    if not key.startswith("wallpapers/"):
        abort(403)
    return send_file(path, mimetype=item.mime_type or None, conditional=True, max_age=3600)


def _get_or_404(wallpaper_id: uuid.UUID) -> Wallpaper:
    item = db.session.execute(
        select(Wallpaper).where(
            Wallpaper.id == wallpaper_id,
            Wallpaper.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if item is None:
        abort(404)
    return item
