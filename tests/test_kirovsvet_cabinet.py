"""Кабинет Кировсвета: телефоны, адрес входа и подпись сессии."""

from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).parents[1]
content = SourceFileLoader("ks_content", str(ROOT / "site" / "content.py")).load_module()
auth = SourceFileLoader("ks_auth", str(ROOT / "site" / "admin_auth.py")).load_module()


def test_phone_becomes_tel_link():
    assert content.tel_from_phone("+7 (8332) 00-00-01") == "+78332000001"
    assert content.tel_from_phone("76-00-00") == "+78332760000"
    assert content.slugify("На Северной загорелись фонари") == "na-severnoy-zagorelis-fonari"


def test_image_is_only_jpeg_png_or_webp():
    assert content.image_ext(b"\xff\xd8\xff\x00") == "jpg"
    assert content.image_ext(b"GIF89a") is None


def test_admin_session_is_signed(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret-for-test")
    token = auth.sign_session("user-1", "Иванова", "csrf-1", now=1_700_000_000)
    assert auth.read_session(token, now=1_700_000_100)["uid"] == "user-1"
    assert auth.read_session(token + "x", now=1_700_000_100) is None
    assert auth.read_session(token, now=1_700_000_000 + auth.MAX_AGE + 5) is None


def test_cabinet_migration_follows_current_head():
    text = (ROOT / "migrations" / "versions" / "070_kirovsvet_site_content.py").read_text(encoding="utf-8")
    assert 'down_revision = "068_work_order_blanks"' in text
    assert "kirovsvet_contacts" in text
    assert "kirovsvet_news" in text
    assert "kirovsvet_schedule" in text
