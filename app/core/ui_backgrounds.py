"""Системные фоны интерфейса и разрешение URL для пользователя."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from flask import url_for


@dataclass(frozen=True)
class BackgroundOption:
    id: str
    title: str
    filename: str | None  # None = без изображения
    thumb: str | None = None


SYSTEM_BACKGROUNDS: tuple[BackgroundOption, ...] = (
    BackgroundOption("none", "Без изображения", None),
    BackgroundOption("kirov_center", "Киров — центр города", "kirov_center.jpg"),
    BackgroundOption("kirov_theater", "Киров — Театральная площадь", "kirov_theater.jpg"),
    BackgroundOption("kirov_embankment", "Киров — набережная", "kirov_embankment.jpg"),
    BackgroundOption("kirov_panorama", "Киров — городская панорама", "kirov_panorama.jpg"),
    BackgroundOption("kirov_evening", "Киров — вечерний город", "kirov_evening.jpg"),
    BackgroundOption("kirov_winter", "Киров — зимний Киров", "kirov_winter.jpg"),
    BackgroundOption("corporate", "Нейтральный корпоративный", "corporate.jpg"),
    BackgroundOption("custom", "Свой фон", None),
)

SYSTEM_BACKGROUND_IDS = frozenset(b.id for b in SYSTEM_BACKGROUNDS if b.id != "custom")
BACKGROUND_STATIC_DIR = "images/backgrounds"

BG_ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
BG_ALLOWED_MIME = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/jpg"}
)
BG_MAX_BYTES = 5 * 1024 * 1024  # 5 МБ


def get_background_option(bg_id: str | None) -> BackgroundOption | None:
    if not bg_id:
        return None
    for item in SYSTEM_BACKGROUNDS:
        if item.id == bg_id:
            return item
    return None


def backgrounds_dir() -> Path:
    from flask import current_app

    return Path(current_app.root_path) / "static" / "images" / "backgrounds"


def resolve_user_background_url(user) -> str | None:
    """URL фонового изображения для текущего пользователя или None."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    bg = (getattr(user, "ui_background", None) or "none").strip()
    if bg in ("", "none"):
        return None
    if bg == "custom":
        key = getattr(user, "ui_background_key", None)
        if not key:
            return None
        return url_for("auth.ui_background_file")
    opt = get_background_option(bg)
    if opt is None or not opt.filename:
        return None
    return url_for("static", filename=f"{BACKGROUND_STATIC_DIR}/{opt.filename}")


def resolve_background_thumb_url(option: BackgroundOption, *, custom_url: str | None = None) -> str | None:
    if option.id == "none":
        return None
    if option.id == "custom":
        return custom_url
    if option.filename:
        return url_for("static", filename=f"{BACKGROUND_STATIC_DIR}/{option.filename}")
    return None
