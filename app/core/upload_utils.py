"""Безопасные имена и сохранение загружаемых файлов."""

from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

_MIME_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/zip": ".zip",
    "text/plain": ".txt",
    "text/csv": ".csv",
}

ALLOWED_UPLOAD_MIME_TYPES = frozenset(_MIME_EXT.keys()) | frozenset(
    {
        "image/jpg",
        "application/x-zip-compressed",
    }
)

ALLOWED_UPLOAD_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".zip",
        ".txt",
        ".csv",
    }
)

# Magic-byte signatures for common types (first bytes)
_MAGIC_PREFIXES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),  # also docx/xlsx
]

PREVIEWABLE_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "application/pdf",
    }
)


@dataclass
class SavedUpload:
    file_name: str
    storage_key: str
    mime_type: str
    file_size: int


class UploadValidationError(ValueError):
    """Некорректный файл загрузки."""


def safe_upload_filename(original: str | None, *, default_stem: str = "file") -> str:
    """Сохраняет расширение файла даже для кириллических имён."""
    if not original or not str(original).strip():
        return f"{default_stem}_{uuid.uuid4().hex[:8]}.bin"

    name = str(original).replace("\\", "/").split("/")[-1].strip()
    path = Path(name)
    ext = path.suffix.lower()

    if not ext and "." in name:
        ext = "." + name.rsplit(".", 1)[-1].lower()

    stem = secure_filename(path.stem)
    if not stem:
        stem = f"{default_stem}_{uuid.uuid4().hex[:8]}"

    if ext and not ext.startswith("."):
        ext = f".{ext}"

    return f"{stem}{ext}" if ext else stem


def resolve_download_filename(
    stored_name: str | None,
    *,
    storage_key: str | None = None,
    mime_type: str | None = None,
    default: str = "file",
) -> str:
    """Восстанавливает имя файла с расширением для скачивания."""
    name = (stored_name or "").strip()

    if name and "." in name:
        return name

    if storage_key:
        key_part = Path(storage_key).name
        if "_" in key_part:
            from_key = key_part.split("_", 1)[1]
            if from_key and "." in from_key:
                return from_key

    ext = _MIME_EXT.get(mime_type or "")
    if not ext and mime_type:
        guessed = mimetypes.guess_extension(mime_type.split(";")[0].strip())
        if guessed:
            ext = guessed

    if name:
        if ext and not name.lower().endswith(ext):
            if ext.lstrip(".").lower() == name.lower():
                return f"file{ext}"
            return f"{name}{ext}"
        return name

    return f"{default}{ext or '.bin'}"


def is_image_mime(mime_type: str | None) -> bool:
    return bool(mime_type and mime_type.lower().startswith("image/"))


def is_previewable_mime(mime_type: str | None) -> bool:
    if not mime_type:
        return False
    mime = mime_type.lower().split(";")[0].strip()
    return mime in PREVIEWABLE_MIME_TYPES or mime.startswith("image/")


def collect_upload_files(form_field_data, request_files_list=None) -> list[FileStorage]:
    """Собирает список FileStorage из MultipleFileField / getlist."""
    files: list[FileStorage] = []
    if form_field_data:
        if isinstance(form_field_data, (list, tuple)):
            files.extend([f for f in form_field_data if f and getattr(f, "filename", None)])
        elif getattr(form_field_data, "filename", None):
            files.append(form_field_data)
    if not files and request_files_list:
        files.extend([f for f in request_files_list if f and getattr(f, "filename", None)])
    return files


def _normalize_mime(mime_type: str | None) -> str:
    if not mime_type:
        return "application/octet-stream"
    mime = mime_type.lower().split(";")[0].strip()
    if mime == "image/jpg":
        return "image/jpeg"
    if mime == "application/x-zip-compressed":
        return "application/zip"
    return mime


def _sniff_mime(header: bytes) -> str | None:
    for prefix, mime in _MAGIC_PREFIXES:
        if header.startswith(prefix):
            return mime
    return None


def _max_file_bytes() -> int:
    # Per-file soft cap: min(MAX_CONTENT_LENGTH, MAX_UPLOAD_FILE_MB)
    total = int(current_app.config.get("MAX_CONTENT_LENGTH") or 64 * 1024 * 1024)
    per_mb = int(current_app.config.get("MAX_UPLOAD_FILE_MB") or 32)
    return min(total, max(1, per_mb) * 1024 * 1024)


def validate_upload(file_storage: FileStorage) -> tuple[str, str]:
    """Проверяет расширение/MIME. Возвращает (safe_name, normalized_mime)."""
    if file_storage is None or not file_storage.filename:
        raise UploadValidationError("Файл не выбран.")

    original_name = safe_upload_filename(file_storage.filename)
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise UploadValidationError(
            f"Тип файла «{ext or 'без расширения'}» не разрешён. "
            f"Допустимо: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}."
        )

    claimed = _normalize_mime(file_storage.mimetype)
    header = file_storage.stream.read(16) if hasattr(file_storage, "stream") else b""
    try:
        file_storage.stream.seek(0)
    except Exception:
        pass

    sniffed = _sniff_mime(header) if header else None
    mime = sniffed or claimed

    # Office Open XML also starts with PK — allow by extension
    if mime == "application/zip" and ext in {".docx", ".xlsx"}:
        mime = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if ext == ".docx"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    if mime not in ALLOWED_UPLOAD_MIME_TYPES and claimed not in ALLOWED_UPLOAD_MIME_TYPES:
        # text/plain / csv may not have strong magic
        if ext in {".txt", ".csv"} and claimed.startswith("text/"):
            mime = claimed if claimed in ALLOWED_UPLOAD_MIME_TYPES else "text/plain"
        else:
            raise UploadValidationError(
                f"MIME-тип «{claimed}» не разрешён для загрузки."
            )

    if mime not in ALLOWED_UPLOAD_MIME_TYPES:
        mime = claimed if claimed in ALLOWED_UPLOAD_MIME_TYPES else next(
            (m for m, e in _MIME_EXT.items() if e == ext), claimed
        )

    return original_name, mime


def save_upload(file_storage: FileStorage, *, relative_dir: str) -> SavedUpload:
    """Сохраняет файл на диск под UPLOAD_FOLDER/{relative_dir}/."""
    original_name, mime_type = validate_upload(file_storage)

    upload_root: Path = current_app.config["UPLOAD_FOLDER"]
    relative_key = f"{relative_dir.strip('/')}/{uuid.uuid4()}_{original_name}"
    absolute_path = upload_root / relative_key
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    file_storage.save(absolute_path)

    file_size = absolute_path.stat().st_size
    max_bytes = _max_file_bytes()
    if file_size <= 0:
        absolute_path.unlink(missing_ok=True)
        raise UploadValidationError("Пустой файл.")
    if file_size > max_bytes:
        absolute_path.unlink(missing_ok=True)
        limit_mb = max(1, max_bytes // (1024 * 1024))
        raise UploadValidationError(f"Файл слишком большой. Лимит на один файл — {limit_mb} МБ.")

    return SavedUpload(
        file_name=original_name,
        storage_key=relative_key.replace("\\", "/"),
        mime_type=mime_type,
        file_size=file_size,
    )
