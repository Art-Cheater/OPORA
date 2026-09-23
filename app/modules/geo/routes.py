"""Единый геокодер, подъезды и маршрут. Браузер не вызывает Nominatim и Valhalla напрямую."""

from __future__ import annotations

from flask import current_app, jsonify, request
from flask_login import login_required
from sqlalchemy import select

from app.core.address.normalize import fold
from app.core.decorators import any_permission_required
from app.core.geo.bbox import BboxError, parse_bbox
from app.core.geo.quality import precision_of
from app.core.routing import RoutingError, RoutingService
from app.extensions import db
from app.models.auth.constants import (
    PERM_AGREEMENTS_VIEW,
    PERM_DEFECTS_VIEW,
    PERM_IRZ_VIEW,
    PERM_OBJECTS_VIEW,
    PERM_REQUESTS_VIEW,
    PERM_WAYBILLS_VIEW,
)
from app.models.geo.directory import GeoEntrance, GeoGeocodeCache
from app.modules.geo.blueprint import geo_bp

_VIEW = (
    PERM_REQUESTS_VIEW,
    PERM_DEFECTS_VIEW,
    PERM_WAYBILLS_VIEW,
    PERM_AGREEMENTS_VIEW,
    PERM_OBJECTS_VIEW,
    PERM_IRZ_VIEW,
)


def _suggestion_payload(item, token: str | None = None) -> dict:
    data = item.as_dict()
    data["precision"] = precision_of(item)
    data["provider"] = item.address_source
    if token:
        data["selection_token"] = token
    return data


def _cache_get(key: str):
    try:
        with db.session.begin_nested():
            row = db.session.scalar(
                select(GeoGeocodeCache).where(
                    GeoGeocodeCache.cache_key == key,
                    GeoGeocodeCache.deleted_at.is_(None),
                )
            )
            if row is None or not isinstance(row.payload, list):
                return None
            return list(row.payload)
    except Exception:
        return None


def _cache_put(key: str, provider: str, payload: list) -> None:
    try:
        with db.session.begin_nested():
            row = db.session.scalar(select(GeoGeocodeCache).where(GeoGeocodeCache.cache_key == key))
            if row is None:
                db.session.add(GeoGeocodeCache(cache_key=key[:400], provider=provider[:32], payload=payload))
            else:
                row.provider = provider[:32]
                row.payload = payload
                row.deleted_at = None
        db.session.commit()
    except Exception:
        db.session.rollback()


@geo_bp.get("/geo/config")
@login_required
@any_permission_required(*_VIEW)
def config():
    return jsonify(
        {
            "style_url": current_app.config.get("MAPLIBRE_STYLE_URL"),
            "center": [current_app.config.get("MAP_CENTER_LNG"), current_app.config.get("MAP_CENTER_LAT")],
            "zoom": current_app.config.get("MAP_ZOOM"),
            "min_zoom": current_app.config.get("MAP_MIN_ZOOM"),
            "max_zoom": current_app.config.get("MAP_MAX_ZOOM"),
            "entrance_min_zoom": current_app.config.get("MAP_ENTRANCE_MIN_ZOOM"),
            "geocoder": "/api/geo/search",
            "reverse": "/api/geo/reverse",
            "routing": "/api/routes",
            "routing_configured": RoutingService.is_configured(),
            "provider": current_app.config.get("GEOCODING_PROVIDER"),
        }
    )


@geo_bp.get("/geo/search")
@login_required
@any_permission_required(*_VIEW)
def search():
    from app.core.address import get_address_suggestion_service, make_address_selection_token

    query = " ".join((request.args.get("q") or "").split())
    if len(query) < 3:
        return jsonify({"suggestions": []})
    scope = (request.args.get("scope") or "").strip().lower()
    cache_key = f"search|{scope}|{fold(query)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify({"suggestions": cached, "cached": True})
    service = get_address_suggestion_service()
    try:
        if scope == "settlement":
            suggestions = service.suggest_settlement(query)
        else:
            suggestions = service.suggest(query)
    except Exception:
        current_app.logger.exception("geo search failed")
        return jsonify({"ok": False, "message": "Сервис адресов временно недоступен.", "suggestions": []}), 503
    payload = [_suggestion_payload(item, make_address_selection_token(item)) for item in suggestions]
    _cache_put(cache_key, str(current_app.config.get("GEOCODING_PROVIDER") or "geocoder"), payload)
    return jsonify({"suggestions": payload, "cached": False})


@geo_bp.get("/geo/reverse")
@login_required
@any_permission_required(*_VIEW)
def reverse():
    from app.core.address import get_address_suggestion_service

    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Нужны числовые lat и lon."}), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"ok": False, "message": "Координаты вне допустимого диапазона."}), 400
    cache_key = f"reverse|{lat:.5f}|{lon:.5f}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify({"ok": True, "suggestion": cached[0], "cached": True})
    try:
        found = get_address_suggestion_service().reverse(lat, lon)
    except Exception:
        current_app.logger.exception("geo reverse failed")
        return jsonify({"ok": False, "message": "Сервис адресов временно недоступен."}), 503
    if found is None:
        return jsonify({"ok": False, "message": "Адрес для этой точки не найден."}), 404
    payload = _suggestion_payload(found)
    _cache_put(cache_key, str(found.address_source or "geocoder"), [payload])
    return jsonify({"ok": True, "suggestion": payload, "cached": False})


@geo_bp.get("/geo/entrances")
@login_required
@any_permission_required(*_VIEW)
def entrances():
    try:
        bbox = parse_bbox(request.args)
        zoom = float(request.args.get("zoom") or 0)
    except (BboxError, TypeError, ValueError) as exc:
        message = str(exc) if isinstance(exc, BboxError) else "Нужны bbox и zoom."
        return jsonify({"ok": False, "message": message, "geojson": {"type": "FeatureCollection", "features": []}}), 400
    minimum = float(current_app.config.get("MAP_ENTRANCE_MIN_ZOOM") or 17)
    if bbox is None or zoom < minimum:
        return jsonify(
            {
                "ok": True,
                "hidden": True,
                "geojson": {"type": "FeatureCollection", "features": []},
                "message": f"Подъезды показываются с масштаба {int(minimum)}.",
            }
        )
    min_lat, max_lat, min_lon, max_lon = bbox
    rows = db.session.scalars(
        select(GeoEntrance)
        .where(
            GeoEntrance.deleted_at.is_(None),
            GeoEntrance.latitude >= min_lat,
            GeoEntrance.latitude <= max_lat,
            GeoEntrance.longitude >= min_lon,
            GeoEntrance.longitude <= max_lon,
        )
        .limit(500)
    )
    features = []
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(row.longitude), float(row.latitude)]},
                "properties": {
                    "ref": row.ref or "",
                    "name": row.name or "",
                    "settlement": row.settlement_name or "",
                    "street": row.street_name or "",
                    "house": row.house_number or "",
                    "address_text": row.address_text or "",
                    "entrance_type": row.entrance_type or "",
                    "lat": float(row.latitude),
                    "lon": float(row.longitude),
                },
            }
        )
    return jsonify({"ok": True, "hidden": False, "geojson": {"type": "FeatureCollection", "features": features}})


@geo_bp.post("/routes")
@login_required
@any_permission_required(*_VIEW)
def routes():
    body = request.get_json(silent=True) or {}
    if body.get("optimize"):
        return jsonify(
            {
                "ok": False,
                "code": "optimization_not_configured",
                "message": "Оптимизация порядка точек не включена. Маршрут строится в заданном порядке.",
            }
        ), 409
    raw = body.get("points")
    if not isinstance(raw, list):
        return jsonify({"ok": False, "code": "invalid_points", "message": "Передайте список точек."}), 400
    mode = str(body.get("mode") or "driving").strip().lower()
    profile = "car" if mode in {"driving", "car", "auto"} else mode
    points = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            return jsonify({"ok": False, "code": "invalid_points", "message": "Точка маршрута указана неверно."}), 400
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon", item.get("lng")))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "code": "invalid_coordinates", "message": "Координаты маршрута указаны неверно."}), 400
        points.append({"id": str(item.get("id") or index), "order": index, "lat": lat, "lon": lon})
    try:
        route = RoutingService.build_route([(point["lat"], point["lon"]) for point in points], profile=profile)
    except RoutingError as exc:
        return jsonify({"ok": False, "code": exc.code, "message": exc.message, "ordered_stops": points})
    return jsonify(
        {
            "ok": True,
            "geometry": route["geometry"],
            "distance_m": route["distance_m"],
            "duration_s": route["duration_s"],
            "ordered_stops": points,
            "legs": route.get("legs") or [],
            "provider": route.get("provider"),
            "warnings": route.get("warnings") or [],
        }
    )
