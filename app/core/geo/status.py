"""Сводка географии и проверки входа. Секреты сюда не попадают."""

from __future__ import annotations

from urllib.request import urlopen

from sqlalchemy import func, select

from app.extensions import db
from app.models.geo.directory import GeoEntrance, GeoHouse, GeoSettlement, GeoStreet


def _count(model) -> int:
    return int(db.session.scalar(select(func.count()).select_from(model).where(model.deleted_at.is_(None))) or 0)


def geocoder_reachable(config) -> bool:
    url = str(config.get("NOMINATIM_BASE_URL") or "").strip()
    if not url:
        return False
    try:
        with urlopen(url, timeout=3) as response:  # nosec B310
            return int(getattr(response, "status", 200) or 200) < 500
    except Exception:
        return False


def geo_status_lines(config, *, reachable: bool | None = None) -> list[str]:
    settlements = _count(GeoSettlement)
    streets = _count(GeoStreet)
    houses = _count(GeoHouse)
    entrances = _count(GeoEntrance)
    last_entrance = db.session.scalar(
        select(func.max(GeoEntrance.updated_at)).where(GeoEntrance.deleted_at.is_(None))
    )
    provider = str(config.get("GEOCODING_PROVIDER") or "nominatim")
    if reachable is None:
        reachable = geocoder_reachable(config)
    site_key = bool(str(config.get("TURNSTILE_SITE_KEY") or "").strip())
    secret = bool(str(config.get("TURNSTILE_SECRET_KEY") or "").strip())
    captcha = bool(config.get("CAPTCHA_ENABLED"))
    style = str(config.get("MAPLIBRE_STYLE_URL") or "")
    last_text = last_entrance.isoformat(sep=" ", timespec="minutes") if last_entrance is not None else "нет"
    return [
        "ADDRESS DIRECTORY",
        f"Settlements: {settlements}",
        f"Streets: {streets}",
        f"Houses: {houses}",
        "",
        "ENTRANCES",
        f"Count: {entrances}",
        f"Last import: {last_text}",
        "",
        "GEOCODER",
        f"Provider: {provider}",
        "Configured: yes",
        f"Reachable: {'yes' if reachable else 'no'}",
        "",
        "MAP",
        f"Style: {style or 'не задан'}",
        f"Configured: {'yes' if style else 'no'}",
        "",
        "CAPTCHA",
        f"Enabled: {'yes' if captcha else 'no'}",
        f"Site key configured: {'yes' if site_key else 'no'}",
        f"Secret configured: {'yes' if secret else 'no'}",
        "",
        "ROUTING",
        "Disabled / not in current scope",
    ]


def security_status_lines(config) -> list[str]:
    site_key = bool(str(config.get("TURNSTILE_SITE_KEY") or "").strip())
    secret = bool(str(config.get("TURNSTILE_SECRET_KEY") or "").strip())
    enabled = bool(config.get("CAPTCHA_ENABLED"))
    return [
        "CAPTCHA",
        f"Enabled: {'yes' if enabled else 'no'}",
        f"Site key configured: {'yes' if site_key else 'no'}",
        f"Secret configured: {'yes' if secret else 'no'}",
        "Hostname: добавьте в Cloudflare Turnstile домен, с которого открывается сайт.",
    ]
