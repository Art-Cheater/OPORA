"""Сводка географии и проверки входа. Секреты сюда не попадают."""

from __future__ import annotations

from pathlib import Path
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


def _data_files(directory: str) -> tuple[str, str]:
    try:
        path = Path(directory)
        if not path.is_dir():
            return "not found", "not found"
        gar = any(path.glob("*.zip"))
        pbf = any(item.is_file() and item.name.casefold().endswith(".pbf") for item in path.iterdir())
        return ("found" if gar else "not found", "found" if pbf else "not found")
    except OSError:
        return "not found", "not found"


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
    host_dir = str(config.get("GEO_DATA_HOST_PATH") or "/opt/opora/data/geo")
    container_dir = str(config.get("GEO_DATA_CONTAINER_PATH") or "/data/geo")
    gar_state, pbf_state = _data_files(container_dir)
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
        "",
        "GEO DATA",
        f"Host directory: {host_dir}",
        f"Container directory: {container_dir}",
        f"GAR archive: {gar_state}",
        f"OSM PBF: {pbf_state}",
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
