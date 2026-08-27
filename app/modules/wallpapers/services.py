"""Сервис каталога обоев (админ)."""

from __future__ import annotations

from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.core.ui_backgrounds import (
    BG_ALLOWED_EXTENSIONS,
    BG_ALLOWED_MIME,
    BG_MAX_BYTES,
    wallpaper_bg_id,
)
from app.core.upload_utils import (
    UploadValidationError,
    resolve_storage_path,
    save_upload,
    validate_upload,
)
from app.extensions import db
from app.models.auth.user import User
from app.models.ui.wallpaper import Wallpaper
from sqlalchemy import select, update


class WallpaperService:
    @staticmethod
    def list_all() -> list[Wallpaper]:
        return list(
            db.session.execute(
                select(Wallpaper)
                .where(Wallpaper.deleted_at.is_(None))
                .order_by(Wallpaper.sort_order.asc(), Wallpaper.created_at.desc())
            )
            .scalars()
            .all()
        )

    @classmethod
    def create(cls, *, title: str, file_storage: FileStorage, user_id) -> Wallpaper:
        title = (title or "").strip() or "Обои"
        saved = cls._save_image(file_storage)
        item = Wallpaper(
            title=title[:200],
            storage_key=saved.storage_key,
            mime_type=saved.mime_type,
            file_size=saved.file_size,
            sort_order=100,
            is_active=True,
            created_by=user_id,
            updated_by=user_id,
        )
        db.session.add(item)
        db.session.commit()
        return item

    @classmethod
    def update_meta(cls, item: Wallpaper, *, title: str | None = None, is_active: bool | None = None, user_id=None) -> Wallpaper:
        if title is not None:
            item.title = (title or "").strip()[:200] or item.title
        if is_active is not None:
            item.is_active = bool(is_active)
            if not item.is_active:
                cls._reset_users_using(item)
        if user_id is not None:
            item.updated_by = user_id
        db.session.commit()
        return item

    @classmethod
    def soft_delete(cls, item: Wallpaper, *, user_id=None) -> None:
        cls._reset_users_using(item)
        cls._delete_file(item.storage_key)
        item.soft_delete(deleted_by=user_id)
        db.session.commit()

    @staticmethod
    def _reset_users_using(item: Wallpaper) -> None:
        bg_id = wallpaper_bg_id(item.id)
        db.session.execute(
            update(User)
            .where(User.ui_background == bg_id, User.deleted_at.is_(None))
            .values(ui_background="none")
        )

    @classmethod
    def _save_image(cls, file_storage: FileStorage):
        if file_storage is None or not getattr(file_storage, "filename", None):
            raise UploadValidationError("Файл не выбран.")
        original_name, mime = validate_upload(file_storage)
        ext = Path(original_name).suffix.lower()
        if ext not in BG_ALLOWED_EXTENSIONS:
            raise UploadValidationError("Допустимы только JPG, PNG или WebP.")
        if mime not in BG_ALLOWED_MIME and not str(mime).startswith("image/"):
            raise UploadValidationError("Файл должен быть изображением.")

        pos = file_storage.stream.tell()
        file_storage.stream.seek(0, 2)
        size = file_storage.stream.tell()
        file_storage.stream.seek(pos)
        if size > BG_MAX_BYTES:
            raise UploadValidationError("Файл слишком большой. Лимит — 5 МБ.")

        saved = save_upload(file_storage, relative_dir="wallpapers")
        if saved.file_size > BG_MAX_BYTES:
            resolve_storage_path(saved.storage_key).unlink(missing_ok=True)
            raise UploadValidationError("Файл слишком большой. Лимит — 5 МБ.")
        return saved

    @staticmethod
    def _delete_file(storage_key: str | None) -> None:
        if not storage_key:
            return
        try:
            resolve_storage_path(storage_key).unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        except Exception:
            current_app.logger.exception("Не удалось удалить файл обоев")
