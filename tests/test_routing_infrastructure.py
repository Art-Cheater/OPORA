from __future__ import annotations

import json
from decimal import Decimal
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


def test_web_gunicorn_command_is_built_by_entrypoint_without_shell_expansion():
    """Environment values must not be accidentally parsed as Gunicorn CLI args."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert 'command: ["gunicorn"]' in compose
    assert 'CMD ["gunicorn"]' in dockerfile
    assert 'command: ["sh", "-c"' not in compose
    assert "\n      - sh\n      - -c\n" not in compose
    assert 'if [ "${1:-}" = "gunicorn" ]; then' in entrypoint
    assert 'export GUNICORN_CMD_ARGS=""' in entrypoint
    assert "set -- gunicorn wsgi:app" in entrypoint
    web_section = compose.split("\n  nginx:", 1)[0]
    assert "DB_POOL_SIZE" not in web_section
    assert "EIS_SSL_VERIFY" not in web_section


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
    assert result.exit_code == 0
    assert "Routing: disabled" in result.output
    assert "ROUTING_PROVIDER and ROUTING_BASE_URL" in result.output


def test_check_routing_hides_connection_traceback(app, monkeypatch):
    import app.core.routing as routing

    with app.app_context():
        app.config.update(ROUTING_PROVIDER="valhalla", VALHALLA_BASE_URL="http://valhalla:8002")
        monkeypatch.setattr(routing, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("connection refused")))
        result = app.test_cli_runner().invoke(args=["check-routing"])
    assert result.exit_code != 0
    assert "routing_unavailable" in result.output
    assert "Traceback" not in result.output


def test_routing_uses_primary_url_and_never_fakes_a_straight_line(app):
    from app.core.routing import RoutingError, RoutingService

    with app.app_context():
        app.config.update(ROUTING_PROVIDER="valhalla", ROUTING_BASE_URL="", VALHALLA_BASE_URL="")
        assert RoutingService.is_configured() is False
        try:
            RoutingService.build_route([(58.6, 49.6), (58.61, 49.61)])
        except RoutingError as exc:
            assert exc.code == "routing_not_configured"
        else:
            raise AssertionError("маршрут не должен подменяться прямой линией")


def test_map_address_parser_handles_lists_ranges_and_regular_address():
    from app.core.address.map_points import split_map_address_parts

    assert len(split_map_address_parts("Лепсе 12, 23, 34")[0]) == 3
    assert len(split_map_address_parts("Лепсе 12. 23. 34")[0]) == 3
    assert len(split_map_address_parts("Лепсе 12; 23; 34")[0]) == 3
    assert len(split_map_address_parts("Даниловский проезд 7, 9, 9а, 11, 11а")[0]) == 5
    assert len(split_map_address_parts("Рейдовая 1-4")[0]) == 4
    assert split_map_address_parts("Киров, ул. Ленина, 15")[0] == ["Киров, ул. Ленина, 15"]


def test_routing_setup_is_separate_from_deploy_and_data_is_excluded():
    prepare = ROOT / "scripts/routing/prepare-routing.sh"
    assert prepare.is_file()
    assert "scripts/routing/prepare-routing.sh" not in (ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/data/routing/*" in ignored and "/data/osrm/*" in ignored and "*.osrm*" in ignored


def test_map_stats_reports_coordinate_coverage(app):
    with app.app_context():
        result = app.test_cli_runner().invoke(args=["map-stats"])
    assert result.exit_code == 0
    assert "requests: total=" in result.output
    assert "defects: total=" in result.output
    assert "works_not_routable=" in result.output


def _missing_coordinate_request(app, *, number="26-9950", address="Лепсе 12, 13", village=False):
    from app.extensions import db
    from app.models.requests.request import Request
    from app.models.requests.request_journal import RequestJournal
    from app.models.requests.request_status import RequestStatus

    with app.app_context():
        journal = db.session.scalar(
            db.select(RequestJournal).where(
                RequestJournal.code == ("oktyabrsky_villages" if village else "requests")
            )
        )
        status = db.session.scalar(db.select(RequestStatus).where(RequestStatus.deleted_at.is_(None)))
        request = Request(
            number=number,
            title="repair QA",
            address=address,
            normalized_address=address,
            applicant_name="QA",
            priority="medium",
            status_id=status.id,
            journal_id=journal.id,
            address_source="village_manual" if village else None,
        )
        db.session.add(request)
        db.session.commit()
        return request.id


def test_coordinate_repair_dry_run_prints_progress_and_does_not_write(app):
    request_id = _missing_coordinate_request(app)
    with app.app_context():
        result = app.test_cli_runner().invoke(
            args=["repair-work-coordinates", "--entity", "requests", "--only-missing", "--build-points", "--dry-run", "--verbose"]
        )
        from app.extensions import db
        from app.models.requests.request import Request

        request = db.session.get(Request, request_id)
    assert result.exit_code == 0
    assert "[1/1] request 26-9950: parsed:" in result.output
    assert "would_attempt_geocode" in result.output
    assert "would_create_points" in result.output
    assert "dry_run=1" in result.output
    assert request.latitude is None and request.longitude is None


def test_coordinate_repair_limits_parts_and_no_geocode_never_calls_provider(app, monkeypatch):
    _missing_coordinate_request(app, address="Лепсе 12, 13, 14, 15")
    monkeypatch.setattr(
        "app.modules.requests.services.RequestService._geocode_latlng",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )
    with app.app_context():
        result = app.test_cli_runner().invoke(
            args=["repair-work-coordinates", "--entity", "requests", "--only-missing", "--build-points", "--no-geocode", "--max-geocode-parts", "3"]
        )
    assert result.exit_code == 0
    assert "geocode parts limited: 3/4" in result.output
    assert "skipped: no_geocode" in result.output
    assert "no_geocode=1" in result.output


def test_coordinate_repair_creates_multiple_points_without_repeating_geocoding(app, monkeypatch):
    request_id = _missing_coordinate_request(app)
    calls = []

    def geocode(part, *, timeout_seconds=None):
        calls.append((part, timeout_seconds))
        return (Decimal("58.6000000"), Decimal("49.6700000"))

    monkeypatch.setattr("app.modules.requests.services.RequestService._geocode_latlng", geocode)
    with app.app_context():
        result = app.test_cli_runner().invoke(
            args=["repair-work-coordinates", "--entity", "requests", "--only-missing", "--build-points", "--verbose"]
        )
        from app.extensions import db
        from app.models.maps.work_map_point import WorkMapPoint
        from app.models.requests.request import Request

        request = db.session.get(Request, request_id)
        points = list(db.session.scalars(db.select(WorkMapPoint).where(WorkMapPoint.entity_id == request_id)))
    assert result.exit_code == 0
    assert "created map_points=2" in result.output
    assert len(calls) == 2
    assert len(points) == 2
    assert request.latitude == Decimal("58.6000000")


def test_coordinate_repair_skips_village_free_text_and_timeout(app, monkeypatch):
    _missing_coordinate_request(app, number="26-9951", address="д. Башарово, Центральная 12", village=True)
    _missing_coordinate_request(app, number="26-9952", address="Лепсе 12")

    def timeout(*_args, **_kwargs):
        raise TimeoutError()

    monkeypatch.setattr("app.modules.requests.services.RequestService._geocode_latlng", timeout)
    with app.app_context():
        result = app.test_cli_runner().invoke(
            args=["repair-work-coordinates", "--entity", "requests", "--only-missing", "--build-points"]
        )
    assert result.exit_code == 0
    assert "request 26-9951: skipped: village_free_text" in result.output
    assert "request 26-9952: skipped: geocoder_timeout" in result.output
