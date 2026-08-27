"""Каталог обоев и URL фонов пользователя."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from flask import url_for
from sqlalchemy import select

from app.extensions import db
from app.models.ui.wallpaper import Wallpaper

BG_ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
BG_ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "image/jpg"})
BG_MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class BackgroundOption:
    id: str
    title: str
    thumb: str | None = None


def wallpaper_bg_id(wallpaper_id: uuid.UUID | str) -> str:
    return f"wp:{wallpaper_id}"


def parse_wallpaper_id(bg: str) -> uuid.UUID | None:
    raw = (bg or "").strip()
    if not raw.startswith("wp:"):
        return None
    try:
        return uuid.UUID(raw[3:])
    except ValueError:
        return None


def list_active_wallpapers() -> list[Wallpaper]:
    return list(
        db.session.execute(
            select(Wallpaper)
            .where(
                Wallpaper.deleted_at.is_(None),
                Wallpaper.is_active.is_(True),
            )
            .order_by(Wallpaper.sort_order.asc(), Wallpaper.created_at.desc())
        )
        .scalars()
        .all()
    )


def get_active_wallpaper(wallpaper_id: uuid.UUID) -> Wallpaper | None:
    return db.session.execute(
        select(Wallpaper).where(
            Wallpaper.id == wallpaper_id,
            Wallpaper.deleted_at.is_(None),
            Wallpaper.is_active.is_(True),
        )
    ).scalar_one_or_none()


def resolve_user_background_url(user) -> str | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    bg = (getattr(user, "ui_background", None) or "none").strip()
    if bg in ("", "none"):
        return None
    if bg == "custom":
        if not getattr(user, "ui_background_key", None):
            return None
        return url_for("auth.ui_background_file")
    wp_id = parse_wallpaper_id(bg)
    if wp_id is None:
        return None
    wp = get_active_wallpaper(wp_id)
    if wp is None:
        return None
    return url_for("wallpapers.file", wallpaper_id=wp.id)


def build_background_options(user) -> list[dict]:
    """Опции для панели внешнего вида."""
    bg = (getattr(user, "ui_background", None) or "none") if user else "none"
    custom_url = None
    if user and bg == "custom" and user.ui_background_key:
        custom_url = url_for("auth.ui_background_file")

    options: list[dict] = [
        {
            "id": "none",
            "title": "Без изображения",
            "thumb": None,
            "selected": bg == "none",
        }
    ]
    for wp in list_active_wallpapers():
        opt_id = wallpaper_bg_id(wp.id)
        options.append(
            {
                "id": opt_id,
                "title": wp.title,
                "thumb": url_for("wallpapers.file", wallpaper_id=wp.id),
                "selected": bg == opt_id,
            }
        )
    if custom_url or (user and user.ui_background_key):
        options.append(
            {
                "id": "custom",
                "title": "Свой фон",
                "thumb": custom_url or url_for("auth.ui_background_file"),
                "selected": bg == "custom",
            }
        )
    return options
