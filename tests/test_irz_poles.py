"""Street-lighting poles: Excel import, list/search, detail page, bbox GeoJSON and permissions."""

from pathlib import Path

import openpyxl
import pytest

from app.extensions import db
from app.models.auth.associations import RolePermission
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.irz import LightPole
from app.modules.auth.services import AuthService
from app.modules.irz import poles

HEADER = ("Номер опоры", "Название светильника", "Широта", "Долгота", "Кол-во, шт")
REAL_FILE = Path(__file__).resolve().parents[1] / "опоры.xlsx"


def _xlsx(path, rows, header=HEADER):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Лист1"
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def _login(client, email, password="pass12345"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def _user_with(app, email, codes):
    with app.app_context():
        role = Role(code=f"qa_{email.split('@')[0].replace('-', '_')}", name=email, description="QA")
        db.session.add(role)
        db.session.flush()
        for code in codes:
            perm = db.session.scalar(db.select(Permission).where(Permission.code == code))
            db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.session.commit()
        AuthService.create_user(email, "pass12345", email, role.code)


def _pole(number):
    return db.session.scalar(db.select(LightPole).where(LightPole.pole_number == number))


BASE_ROWS = [
    (1000001, "MAG41-200 (200 Вт)", "58.60199936", "49.66012345", 1),
    (1000001, "MAG41-200 (200 Вт)", "58.60199936", "49.66012345", 1),
    (1000001, "MAG31-130 (130 Вт)", "58.60199936", "49.66012345", 1),
    (1000002, "ЖКУ-150", 58.61, 49.67, "2"),
    (None, "без номера", 58.62, 49.68, 1),
    (1000003, "РКУ-250", "north", "49.69", 1),
    (1000004, "ЖКУ-70", 58.63, 49.7, "abc"),
    ("00123", "ЖКУ-100", 58.64, 49.71, 1.0),
]


def test_import_merges_luminaires_skips_empty_numbers_and_keeps_bad_coordinates_empty(app, tmp_path):
    source = _xlsx(tmp_path / "опоры.xlsx", BASE_ROWS)
    with app.app_context():
        report = poles.import_poles(source)
        assert (report["total"], report["poles"], report["inserted"], report["updated"]) == (8, 5, 5, 0)
        assert (report["merged"], report["skipped"], report["errors"]) == (2, 1, 1)
        assert report["skip_reasons"] == {"пустой номер опоры": 1}
        merged = _pole("1000001")
        assert merged.luminaire_name == "MAG41-200 (200 Вт) × 2; MAG31-130 (130 Вт)"
        assert merged.quantity == 3
        assert (merged.latitude, merged.longitude) == (58.60199936, 49.66012345)
        assert _pole("1000002").quantity == 2
        bad = _pole("1000003")
        assert (bad.latitude, bad.longitude, bad.quantity) == (None, None, 1)
        assert any("1000003" in text and "невалидные координаты" in text for text in report["warnings"])
        assert _pole("1000004").quantity is None
        assert any("1000004" in text and "количество" in text for text in report["warnings"])
        assert _pole("00123").quantity == 1


def test_reimport_is_idempotent_and_updates_changed_rows(app, tmp_path):
    source = _xlsx(tmp_path / "first.xlsx", BASE_ROWS)
    with app.app_context():
        poles.import_poles(source)
        again = poles.import_poles(source)
        assert (again["inserted"], again["updated"], again["unchanged"]) == (0, 0, 5)
        assert db.session.scalar(db.select(db.func.count()).select_from(LightPole)) == 5
        changed = _xlsx(tmp_path / "second.xlsx", [(1000002, "ЖКУ-250", 58.615, 49.675, 4)])
        report = poles.import_poles(changed)
        assert (report["inserted"], report["updated"], report["unchanged"]) == (0, 1, 0)
        pole = _pole("1000002")
        assert (pole.luminaire_name, pole.latitude, pole.longitude, pole.quantity) == ("ЖКУ-250", 58.615, 49.675, 4)
        assert _pole("1000001") is not None
        assert db.session.scalar(db.select(db.func.count()).select_from(LightPole)) == 5


def test_dry_run_writes_nothing_and_missing_columns_are_reported(app, tmp_path):
    with app.app_context():
        report = poles.import_poles(_xlsx(tmp_path / "a.xlsx", BASE_ROWS), dry_run=True)
        assert report["inserted"] == 5
        assert db.session.scalar(db.select(db.func.count()).select_from(LightPole)) == 0
        with pytest.raises(ValueError, match="Кол-во, шт"):
            poles.import_poles(_xlsx(tmp_path / "b.xlsx", [], header=HEADER[:4]))


def test_cli_imports_default_report_lines(app, tmp_path):
    source = _xlsx(tmp_path / "опоры.xlsx", BASE_ROWS)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["irz-import-poles", "--file", str(source)])
    assert result.exit_code == 0, result.output
    for line in ("Всего строк: 8", "Опор (уникальных номеров): 5", "Добавлено: 5", "Обновлено: 0",
                 "Пропущено: 1", "Ошибок: 1"):
        assert line in result.output
    repeat = runner.invoke(args=["irz-import-poles", "--file", str(source)])
    assert "Добавлено: 0" in repeat.output and "Без изменений: 5" in repeat.output
    missing = runner.invoke(args=["irz-import-poles", "--file", str(tmp_path / "nope.xlsx")])
    assert missing.exit_code != 0 and "Файл не найден" in missing.output


@pytest.mark.skipif(not REAL_FILE.is_file(), reason="опоры.xlsx не положен в корень проекта")
def test_real_file_imports_every_pole_once(app):
    with app.app_context():
        report = poles.import_poles(REAL_FILE)
        assert (report["total"], report["poles"], report["inserted"]) == (4701, 4068, 4068)
        assert (report["merged"], report["skipped"], report["errors"]) == (633, 0, 0)
        assert db.session.scalar(db.select(db.func.sum(LightPole.quantity))) == 4701
        assert db.session.scalar(db.select(db.func.count()).select_from(LightPole).where(LightPole.latitude.is_(None))) == 0
        again = poles.import_poles(REAL_FILE)
        assert (again["inserted"], again["updated"], again["unchanged"]) == (0, 0, 4068)
        found = poles.find_pole("2880041")
        assert found is not None and found.pole_number == "2880041"
        assert found.latitude is not None and found.longitude is not None


def _seed_poles(app, tmp_path):
    with app.app_context():
        poles.import_poles(_xlsx(tmp_path / "seed.xlsx", BASE_ROWS))
        return str(_pole("1000001").id), str(_pole("1000003").id)


def test_list_searches_by_number_and_luminaire_with_total_and_pagination(app, admin_client, tmp_path):
    _seed_poles(app, tmp_path)
    html = admin_client.get("/irz/poles").get_data(as_text=True)
    assert "Найдено: <b>5</b>" in html and "1000001" in html and "MAG31-130" in html
    assert 'class="nav-link active" href="/irz/poles"' in html
    found = admin_client.get("/irz/poles?q=1000002").get_data(as_text=True)
    assert "Найдено: <b>1</b>" in found and "ЖКУ-150" in found
    by_luminaire = admin_client.get("/irz/poles?q=MAG41").get_data(as_text=True)
    assert "Найдено: <b>1</b>" in by_luminaire and "1000001" in by_luminaire
    assert "Найдено: <b>0</b>" in admin_client.get("/irz/poles?q=%25").get_data(as_text=True)
    with app.app_context():
        items, pagination = poles.search_poles("", page=2, per_page=2)
        assert pagination == {"page": 2, "pages": 3, "per_page": 2, "total": 5} and len(items) == 2
        first, _ = poles.search_poles("", page=1, per_page=5)
        assert [pole.pole_number for pole in first][:2] == ["00123", "1000001"]


def test_detail_page_shows_fields_and_small_map(app, admin_client, tmp_path):
    merged_id, bad_id = _seed_poles(app, tmp_path)
    html = admin_client.get(f"/irz/poles/{merged_id}").get_data(as_text=True)
    assert "Опора № 1000001" in html and "MAG41-200 (200 Вт) × 2" in html and "58.60199936" in html
    assert "data-irz-pole-map" in html and 'data-pole-template="/irz/poles/POLE_ID"' in html
    no_coords = admin_client.get(f"/irz/poles/{bad_id}").get_data(as_text=True)
    assert "Координаты не заданы" in no_coords and "data-irz-pole-map" not in no_coords
    assert admin_client.get("/irz/poles/00000000-0000-0000-0000-000000000000").status_code == 404
    assert admin_client.get("/irz/poles/not-a-uuid").status_code == 404


def test_geojson_returns_only_poles_inside_bbox(app, admin_client, tmp_path):
    _seed_poles(app, tmp_path)
    data = admin_client.get("/irz/poles/map.json?bbox=49.65,58.60,49.675,58.615").get_json()
    assert data["type"] == "FeatureCollection" and data["truncated"] is False
    numbers = {feature["properties"]["pole_number"] for feature in data["features"]}
    assert numbers == {"1000001", "1000002"}
    feature = next(item for item in data["features"] if item["properties"]["pole_number"] == "1000001")
    assert feature["geometry"]["coordinates"] == [49.66012345, 58.60199936]
    assert set(feature["properties"]) == {"id", "pole_number", "luminaire_name", "quantity", "lat", "lon"}
    assert feature["properties"]["quantity"] == 3
    everything = admin_client.get("/irz/poles/map.json?min_lat=50&max_lat=60&min_lon=40&max_lon=60").get_json()
    assert len(everything["features"]) == 4
    capped = admin_client.get("/irz/poles/map.json?bbox=40,50,60,60&limit=2").get_json()
    assert len(capped["features"]) == 2 and capped["truncated"] is True
    for query in ("", "?bbox=1,2,3", "?bbox=a,b,c,d", "?bbox=49.7,58.6,49.6,58.7", "?bbox=0,95,1,96"):
        assert admin_client.get(f"/irz/poles/map.json{query}").status_code == 400, query


def test_map_pages_offer_poles_layer_toggle(app, admin_client):
    html = admin_client.get("/irz").get_data(as_text=True)
    assert "data-layer-devices" in html and "data-layer-poles" in html
    assert 'data-poles-url="/irz/poles/map.json"' in html and 'data-pole-template="/irz/poles/POLE_ID"' in html
    kiosk = admin_client.get("/irz/map-display").get_data(as_text=True)
    assert "data-poles-toggle" in kiosk and 'data-poles-url="/irz/poles/map.json"' in kiosk


def test_poles_require_login(client):
    for path in ("/irz/poles", "/irz/poles/map.json?bbox=49,58,50,59"):
        response = client.get(path)
        assert response.status_code == 302 and "/auth/login" in response.headers["Location"]


def test_poles_forbidden_without_irz_permissions(app, client, tmp_path):
    merged_id, _ = _seed_poles(app, tmp_path)
    _user_with(app, "no-irz@test.local", ["requests.view"])
    _login(client, "no-irz@test.local")
    for path in ("/irz/poles", f"/irz/poles/{merged_id}", "/irz/poles/map.json?bbox=49,58,50,59"):
        assert client.get(path).status_code == 403, path


def test_kiosk_role_reads_pole_layer_but_not_pole_pages(app, client, tmp_path):
    merged_id, _ = _seed_poles(app, tmp_path)
    _user_with(app, "pole-screen@test.local", ["irz.map_display"])
    _login(client, "pole-screen@test.local")
    assert client.get("/irz/poles/map.json?bbox=49,58,50,59").status_code == 200
    html = client.get("/irz/map-display").get_data(as_text=True)
    assert 'data-pole-template=""' in html
    assert client.get("/irz/poles").status_code == 403
    assert client.get(f"/irz/poles/{merged_id}").status_code == 403


def test_cli_poles_find_and_deploy_check(app, tmp_path):
    from app.modules.irz import cabinets
    from tests.test_irz_cabinets import _import

    _seed_poles(app, tmp_path)
    found = app.test_cli_runner().invoke(args=["irz-poles-find", "1000001"])
    assert found.exit_code == 0, found.output
    assert "Pole: 1000001" in found.output
    assert app.test_cli_runner().invoke(args=["irz-poles-find", "0"]).exit_code != 0
    with app.app_context():
        _import(tmp_path)
        poles.import_poles(_xlsx(tmp_path / "control.xlsx", [
            (2880041, "MAG31-130 7-01-130-01-1-12-02-206-7-40-66 (130 Вт)", 58.60199936, 49.67259864, 1),
        ]))
    check = app.test_cli_runner().invoke(args=["irz-deploy-check"])
    assert check.exit_code == 0, check.output
    assert "IRZ deploy check: OK" in check.output
    assert "40191143" in check.output and "ИП-6" in check.output and "2880041" in check.output
