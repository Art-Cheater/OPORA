"""Сервис настроек внешнего вида пользователя."""

from __future__ import annotations

from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.core.ui_backgrounds import (
    BG_ALLOWED_EXTENSIONS,
    BG_ALLOWED_MIME,
    BG_MAX_BYTES,
    SYSTEM_BACKGROUND_IDS,
)
from app.core.upload_utils import (
    UploadValidationError,
    resolve_storage_path,
    save_upload,
    validate_upload,
)
from app.extensions import db


class AppearanceService:
    @staticmethod
    def set_theme(user, theme: str | None) -> None:
        if theme in (None, "", "system"):
            user.ui_theme = None
        elif theme in ("light", "dark"):
            user.ui_theme = theme
        else:
            raise ValueError("Некорректная тема.")
        user.updated_by = user.id
        db.session.commit()

    @staticmethod
    def set_background(user, background_id: str) -> None:
        bg = (background_id or "none").strip()
        if bg == "custom":
            if not user.ui_background_key:
                raise ValueError("Сначала загрузите своё изображение.")
            user.ui_background = "custom"
        elif bg in SYSTEM_BACKGROUND_IDS:
            user.ui_background = bg
        else:
            raise ValueError("Неизвестный фон.")
        user.updated_by = user.id
        db.session.commit()

    @classmethod
    def upload_background(cls, user, file_storage: FileStorage) -> str:
        if file_storage is None or not getattr(file_storage, "filename", None):
            raise UploadValidationError("Файл не выбран.")

        original_name, mime = validate_upload(file_storage)
        ext = Path(original_name).suffix.lower()
        if ext not in BG_ALLOWED_EXTENSIONS:
            raise UploadValidationError("Допустимы только JPG, PNG или WebP.")
        if mime not in BG_ALLOWED_MIME and not str(mime).startswith("image/"):
            raise UploadValidationError("Файл должен быть изображением.")

        # Проверка размера до записи (stream)
        pos = file_storage.stream.tell()
        file_storage.stream.seek(0, 2)
        size = file_storage.stream.tell()
        file_storage.stream.seek(pos)
        if size > BG_MAX_BYTES:
            raise UploadValidationError("Фон слишком большой. Лимит — 5 МБ.")

        cls._delete_custom_file(user)
        saved = save_upload(file_storage, relative_dir=f"users/{user.id}/background")
        if saved.file_size > BG_MAX_BYTES:
            path = resolve_storage_path(saved.storage_key)
            path.unlink(missing_ok=True)
            raise UploadValidationError("Фон слишком большой. Лимит — 5 МБ.")

        user.ui_background_key = saved.storage_key
        user.ui_background = "custom"
        user.updated_by = user.id
        db.session.commit()
        return saved.storage_key

    @classmethod
    def clear_custom_background(cls, user) -> None:
        cls._delete_custom_file(user)
        user.ui_background_key = None
        if user.ui_background == "custom":
            user.ui_background = "none"
        user.updated_by = user.id
        db.session.commit()

    @staticmethod
    def _delete_custom_file(user) -> None:
        key = getattr(user, "ui_background_key", None)
        if not key:
            return
        try:
            path = resolve_storage_path(key)
            path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        except Exception:
            current_app.logger.exception("Не удалось удалить старый фон пользователя")
