"""Тесты каталога обоев и выбора фона."""

from __future__ import annotations

import io

from PIL import Image

from app.core.ui_backgrounds import wallpaper_bg_id
from app.extensions import db
from app.models.auth.user import User
from app.models.ui.wallpaper import Wallpaper


def _png_bytes(color=(40, 80, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (128, 72), color).save(buf, format="PNG")
    return buf.getvalue()


def test_wallpapers_admin_page(admin_client):
    page = admin_client.get("/wallpapers/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Обои" in html
    assert "Добавить обои" in html


def test_wallpapers_forbidden_for_executor(client):
    client.post(
        "/auth/login",
        data={"email": "executor@test.local", "password": "pass12345", "submit": "Войти"},
        follow_redirects=True,
    )
    assert client.get("/wallpapers/").status_code in (302, 403)


def test_admin_can_add_wallpaper_and_user_can_select(app):
    admin = app.test_client()
    admin.post(
        "/auth/login",
        data={"email": "admin@opora.ru", "password": "admin123", "submit": "Войти"},
        follow_redirects=True,
    )
    png = _png_bytes()
    res = admin.post(
        "/wallpapers/create",
        data={
            "title": "Киров — тест",
            "image": (io.BytesIO(png), "kirov.png"),
            "submit": "Добавить",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Oboi" in res.data or "добавлены" in res.get_data(as_text=True).lower() or "Киров" in res.get_data(as_text=True)

    with app.app_context():
        wp = (
            db.session.query(Wallpaper)
            .filter(Wallpaper.deleted_at.is_(None), Wallpaper.title == "Киров — тест")
            .one()
        )
        bg_id = wallpaper_bg_id(wp.id)
        wp_id = wp.id

    file_res = admin.get(f"/wallpapers/{wp_id}/file")
    assert file_res.status_code == 200

    # выбор в appearance
    sel = admin.post("/auth/ui/appearance", json={"background": bg_id})
    assert sel.status_code == 200
    assert sel.get_json()["ok"] is True
    with app.app_context():
        user = db.session.execute(
            db.select(User).where(User.email == "admin@opora.ru")
        ).scalar_one()
        assert user.ui_background == bg_id

    # панель внешнего вида показывает обои
    home = admin.get("/").get_data(as_text=True)
    assert "Киров — тест" in home
    assert "Киров — центр" not in home  # старые hardcoded убраны


def test_appearance_rejects_unknown_legacy_bg(admin_client):
    res = admin_client.post(
        "/auth/ui/appearance",
        json={"theme": "light", "background": "kirov_center"},
    )
    assert res.status_code == 400


def test_seed_kirov_wallpapers_and_previews(admin_client, app):
    with app.app_context():
        from app.modules.wallpapers.seed import WallpaperSeedService

        WallpaperSeedService.ensure_kirov_wallpapers()
        items = (
            db.session.query(Wallpaper)
            .filter(
                Wallpaper.deleted_at.is_(None),
                Wallpaper.is_active.is_(True),
                Wallpaper.storage_key.like("wallpapers/seed/%"),
            )
            .all()
        )
        assert len(items) >= 6
        sample = items[0]

    home = admin_client.get("/").get_data(as_text=True)
    assert "Трифонов монастырь" in home or "Театральная площадь" in home
    assert "appearance-bg-card__preview" in home

    file_res = admin_client.get(f"/wallpapers/{sample.id}/file")
    assert file_res.status_code == 200
    assert file_res.mimetype and "image" in file_res.mimetype
