from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_routing_override_uses_private_pinned_official_valhalla_image():
    compose = (ROOT / "docker-compose.routing.yml").read_text(encoding="utf-8")
    assert "valhalla:" in compose
    assert "ghcr.io/valhalla/valhalla-scripted:3.8.3" in compose
    assert "8002:8002" not in compose
    assert "./data/valhalla:/custom_files" in compose


def test_valhalla_data_and_osm_extracts_are_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    docker_ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "/data/valhalla/*" in ignored
    assert "*.osm.pbf" in ignored
    assert "data/" in docker_ignored
    assert "*.osm.pbf" in docker_ignored
    assert (ROOT / "scripts/valhalla/prepare-valhalla.sh").is_file()


def test_main_compose_has_no_valhalla_hard_dependency():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "valhalla:" not in compose
    assert "VALHALLA_BASE_URL" not in compose


def test_web_gunicorn_command_keeps_shell_command_as_single_argument():
    """The entrypoint uses ``exec \"$@\"``, so ``sh -c`` needs one command string."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "    command:\n      - sh\n      - -c\n      - >-\n        unset GUNICORN_CMD_ARGS; exec gunicorn wsgi:app" in compose
    assert "$${WEB_CONCURRENCY:-3}" in compose
    assert "$${GUNICORN_THREADS:-8}" in compose
    assert "exec gunicorn --bind" not in compose


def test_valhalla_provider_uses_internal_url_and_returns_geojson(app, monkeypatch):
    from app.core.routing import RoutingService
    import app.core.routing as routing

    with app.app_context():
        app.config.update(ROUTING_PROVIDER="valhalla", VALHALLA_BASE_URL="http://valhalla:8002")
        monkeypatch.setattr(
            routing,
            "urlopen",
            lambda *_args, **_kwargs: _Response(
                {"trip": {"summary": {"length": 1.2, "time": 130}, "shape": {"type": "LineString", "coordinates": [[49.66, 58.60], [49.67, 58.61]]}}}
            ),
        )
        route = RoutingService.route([(58.60, 49.66), (58.61, 49.67)])
    assert route == {
        "geometry": {"type": "LineString", "coordinates": [[49.66, 58.60], [49.67, 58.61]]},
        "distance_m": 1200,
        "duration_s": 130,
    }


def test_check_routing_prints_clear_message_when_url_is_missing(app):
    with app.app_context():
        app.config.update(ROUTING_PROVIDER="valhalla", VALHALLA_BASE_URL="", ROUTING_BASE_URL="")
        result = app.test_cli_runner().invoke(args=["check-routing"])
    assert result.exit_code != 0
    assert "Провайдер: valhalla" in result.output
    assert "Адрес сервиса: не задан" in result.output
    assert "VALHALLA_BASE_URL" in result.output


def test_check_routing_hides_connection_traceback(app, monkeypatch):
    import app.core.routing as routing

    with app.app_context():
        app.config.update(ROUTING_PROVIDER="valhalla", VALHALLA_BASE_URL="http://valhalla:8002")
        monkeypatch.setattr(routing, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("connection refused")))
        result = app.test_cli_runner().invoke(args=["check-routing"])
    assert result.exit_code != 0
    assert "valhalla недоступен" in result.output
    assert "Traceback" not in result.output
