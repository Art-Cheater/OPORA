"""Сид реальных обоев Кирова в каталог wallpapers."""

from __future__ import annotations

import shutil
from pathlib import Path

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models.ui.wallpaper import Wallpaper

# (seed_key_suffix, title, filename, sort_order)
KIROV_SEED = (
    ("kirov_monastery", "Киров — Трифонов монастырь", "kirov_monastery.jpg", 10),
    ("kirov_theater", "Киров — Театральная площадь", "kirov_theater.jpg", 20),
    ("kirov_ferris", "Киров — колесо обозрения", "kirov_ferris.jpg", 30),
    ("kirov_spasskaya", "Киров — улица Спасская", "kirov_spasskaya.jpg", 40),
    ("kirov_museum", "Киров — музей Циолковского", "kirov_museum.jpg", 50),
    ("kirov_newyear", "Киров — новогодняя площадь", "kirov_newyear.jpg", 60),
)

# Старые заглушки / сгенерированные названия — скрываем при сиде
LEGACY_PLACEHOLDER_TITLES = frozenset(
    {
        "Киров — зимний Киров",
        "Киров — центр города",
        "Киров — набережная",
        "Киров — городская панорама",
        "Киров — вечерний город",
        "Нейтральный корпоративный",
    }
)


class WallpaperSeedService:
    @classmethod
    def seed_dir(cls) -> Path:
        return Path(current_app.root_path) / "seed" / "wallpapers"

    @classmethod
    def ensure_kirov_wallpapers(cls) -> int:
        """Копирует seed-файлы в uploads и создаёт/обновляет записи. Возвращает число upsert."""
        seed_dir = cls.seed_dir()
        upload_root = Path(current_app.config["UPLOAD_FOLDER"])
        created = 0

        for code, title, filename, sort_order in KIROV_SEED:
            src = seed_dir / filename
            if not src.is_file():
                current_app.logger.warning("Нет seed-обоев: %s", src)
                continue

            storage_key = f"wallpapers/seed/{filename}"
            dest = upload_root / "wallpapers" / "seed" / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dest)

            item = db.session.execute(
                select(Wallpaper).where(
                    Wallpaper.storage_key == storage_key,
                    Wallpaper.deleted_at.is_(None),
                )
            ).scalar_one_or_none()

            if item is None:
                item = Wallpaper(
                    title=title,
                    storage_key=storage_key,
                    mime_type="image/jpeg",
                    file_size=int(dest.stat().st_size),
                    sort_order=sort_order,
                    is_active=True,
                )
                db.session.add(item)
                created += 1
            else:
                item.title = title
                item.sort_order = sort_order
                item.is_active = True
                item.mime_type = "image/jpeg"
                item.file_size = int(dest.stat().st_size)

        # Скрыть устаревшие заглушки
        legacy = db.session.execute(
            select(Wallpaper).where(
                Wallpaper.deleted_at.is_(None),
                Wallpaper.title.in_(tuple(LEGACY_PLACEHOLDER_TITLES)),
            )
        ).scalars().all()
        for item in legacy:
            item.is_active = False

        db.session.commit()
        return created
