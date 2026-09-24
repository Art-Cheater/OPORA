"""Mercury serial -> ШУНО directory: Excel import, auto-match after poll, manual re-apply, conflicts."""

from datetime import date, datetime, timezone
from pathlib import Path

import openpyxl
import pytest

from app.extensions import db
from app.models.auth.associations import RolePermission
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.irz import IRZDevice, IRZMeter, MeterCabinetDirectory
from app.modules.auth.services import AuthService
from app.modules.irz import cabinets, service

HEADER = ["Серийный номер", "ШУНО", "ID ШУНО", "Модель", "Установлен", "КТТ", "Широта", "Долгота"]
IMEI_A = "861000000000101"
IMEI_B = "861000000000102"
ROWS = [
    ["40191143", "ИП-6", 221, "Меркурий 230 ART-03 PQRSIDN", "02.03.2020...", "20.00", 58.60934796, 49.68161881],
    [" 37842711 ", "ИП-1324", 60, "Меркурий 230 ART-02 PQRSIN", "-", "1.00", "58,5830841", "49.626019"],
    [39807974, "ПП-601", 243, "Меркурий 230 ART-02 PQRSIN", "22.11.2019...", "1.00", None, None],
    ["40191143*", "ИП-старый", 13, "Меркурий 230 ART-02 PQRSIN", "10.04.2019—27.05.2021", "1.00", 58.1, 49.1],
    [None, "ПП-пусто", 1, "Меркурий 230 ART-02 PQRSIN", "-", "1.00", 58.2, 49.2],
    ["39163742", None, None, "Меркурий 230 ART-02 PQRSIN", "-", "1.00", "север", 49.3],
]


def _workbook(path: Path, rows=ROWS, sheet="Счётчики", header=HEADER) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(header)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return path


def _poll_result(serial):
    return {"success": True, "partial": False, "errors": [], "results": {
        "serial_and_manufacture": {"data": {"serial_number": serial, "date_of_manufacture": "2020-01-10"}, "duration_ms": 300},
        "voltage_phases": {"data": {"a": "230.1", "b": "229.5", "c": "231"}, "duration_ms": 200},
    }}


def _poll(device, monkeypatch, serial=40191143):
    monkeypatch.setattr(service, "_gateway_request", lambda *a, **k: _poll_result(serial))
    return service.poll_device(device, user_id=None, source="AUTO", log_operations=False)


def _device(imei=IMEI_A, **kwargs):
    kwargs.setdefault("name", f"ATM21 {imei}")
    device = IRZDevice(imei=imei, model="ATM21", enabled=True, network_address=0, **kwargs)
    db.session.add(device)
    db.session.commit()
    return device


def _import(tmp_path, rows=ROWS):
    return cabinets.import_meter_directory(_workbook(tmp_path / "meters.xlsx", rows))


def _login_as(app, client, email, codes):
    with app.app_context():
        role = Role(code=f"qa_{email.split('@')[0].replace('-', '_')}", name=email, description="QA")
        db.session.add(role)
        db.session.flush()
        for code in codes:
            permission = db.session.scalar(db.select(Permission).where(Permission.code == code))
            db.session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        db.session.commit()
        AuthService.create_user(email, "pass12345", email, role.code)
    client.post("/auth/login", data={"email": email, "password": "pass12345"})


@pytest.mark.parametrize("raw", [40191143, 40191143.0, "40191143", " 40191143 ", "40 191 143", "40191143.0"])
def test_serial_numeric_and_text_cells_normalize_to_same_key(raw):
    assert cabinets.normalize_serial(raw) == "40191143"


def test_serial_keeps_leading_zeros_for_short_numbers():
    assert cabinets.normalize_serial(1234567) == cabinets.normalize_serial("01234567") == "01234567"
    assert cabinets.normalize_serial(None) is None and cabinets.normalize_serial("  ") is None
    assert cabinets.normalize_serial(True) is None and cabinets.normalize_serial(1.5) is None


def test_import_inserts_rows_skips_history_and_empty_and_nulls_bad_coordinates(app, tmp_path):
    with app.app_context():
        report = _import(tmp_path)
        assert (report["total"], report["inserted"], report["updated"], report["skipped"], report["errors"]) == (6, 4, 0, 2, 0)
        assert report["skip_reasons"] == {"историческая установка (*)": 1, "пустой серийный номер": 1}
        assert any("39163742" in warning and "координаты" in warning for warning in report["warnings"])
        entry = cabinets.find_entry("40191143")
        assert (entry.cabinet_name, entry.cabinet_external_id, entry.meter_model) == ("ИП-6", "221", "Меркурий 230 ART-03 PQRSIDN")
        assert (entry.latitude, entry.longitude, entry.ktt) == (58.60934796, 49.68161881, 20.0)
        assert (entry.installed_at, entry.installed_raw) == (date(2020, 3, 2), "02.03.2020...")
        trimmed = cabinets.find_entry(37842711)
        assert trimmed.meter_serial == "37842711" and trimmed.latitude == 58.5830841 and trimmed.installed_raw is None
        assert cabinets.find_entry("39807974").latitude is None
        no_cabinet = cabinets.find_entry("39163742")
        assert no_cabinet.cabinet_name is None and no_cabinet.latitude is None and no_cabinet.longitude is None


def test_reimport_updates_existing_serial_without_duplicates(app, tmp_path):
    with app.app_context():
        _import(tmp_path)
        changed = [list(row) for row in ROWS]
        changed[0][1] = "ИП-6А"
        report = _import(tmp_path, changed)
        assert (report["inserted"], report["updated"], report["unchanged"]) == (0, 1, 3)
        assert db.session.scalar(db.select(db.func.count(MeterCabinetDirectory.id))) == 4
        assert cabinets.find_entry("40191143").cabinet_name == "ИП-6А"


def test_import_rejects_wrong_sheet_or_missing_columns_without_writing(app, tmp_path):
    with app.app_context():
        with pytest.raises(ValueError, match="Счётчики"):
            cabinets.import_meter_directory(_workbook(tmp_path / "a.xlsx", sheet="Лист1"))
        with pytest.raises(ValueError, match="Широта"):
            cabinets.import_meter_directory(_workbook(tmp_path / "b.xlsx", header=HEADER[:6]))
        assert db.session.scalar(db.select(db.func.count(MeterCabinetDirectory.id))) == 0


def test_new_irz_is_named_and_placed_from_directory_after_serial_is_read(app, admin_client, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device()
        assert device.directory_match_status is None
        result = _poll(device, monkeypatch)
        assert result["quality"] == "GOOD"
        db.session.refresh(device)
        assert device.name == "ИП-6" and (device.latitude, device.longitude) == (58.60934796, 49.68161881)
        assert device.directory_match_status == cabinets.MATCHED and device.directory_matched_at is not None
        meter = db.session.scalar(db.select(IRZMeter))
        assert meter.serial_number == "40191143" and meter.catalog_model == "Меркурий 230 ART-03 PQRSIDN"
        assert meter.model is None and meter.model_source is None
    monkeypatch.setattr(service, "get_devices", lambda: [{"imei": IMEI_A, "ip": "10.0.0.1",
                                                          "last_seen_at": datetime.now(timezone.utc).isoformat()}])
    item = admin_client.get("/irz/api/map").get_json()["items"][0]
    assert item["title"] == "ИП-6" and item["has_coordinates"] and item["status"] == "OK"
    assert item["meter"]["model"] == "Меркурий 230 ART-03 PQRSIDN"
    detail = admin_client.get(f"/irz/api/devices/{IMEI_A}").get_json()
    assert detail["directory"]["entry"]["cabinet_external_id"] == "221"
    assert detail["directory"]["status"] == "MATCHED" and detail["meter"]["catalog_model"].startswith("Меркурий")


def test_unknown_serial_marks_not_found_and_changes_nothing(app, admin_client, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device()
        assert _poll(device, monkeypatch, serial=12345678)["quality"] == "GOOD"
        db.session.refresh(device)
        assert device.name == f"ATM21 {IMEI_A}" and device.latitude is None
        assert (device.directory_match_status, device.directory_match_serial) == ("NOT_FOUND", "12345678")
        assert device.directory_entry_id is None
    monkeypatch.setattr(service, "get_devices", lambda: [{"imei": IMEI_A}])
    detail = admin_client.get(f"/irz/api/devices/{IMEI_A}").get_json()
    assert detail["directory"]["status"] == "NOT_FOUND" and detail["directory"]["entry"] is None
    listed = admin_client.get("/irz/api/directory").get_json()["items"][0]
    assert listed["status"] == "OK" and listed["online"] is True


def test_directory_imported_later_matches_on_next_poll(app, tmp_path, monkeypatch):
    with app.app_context():
        device = _device()
        _poll(device, monkeypatch)
        assert device.directory_match_status == "NOT_FOUND"
        _import(tmp_path)
        _poll(device, monkeypatch)
        assert device.directory_match_status == "MATCHED" and device.name == "ИП-6"


def test_repeated_poll_keeps_manual_name_and_coordinates(app, admin_client, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device()
        _poll(device, monkeypatch)
    response = admin_client.patch(f"/irz/api/devices/{IMEI_A}", json={"name": "ИП-6 (ул. Ленина)",
                                                                      "latitude": "58.7", "longitude": "49.7"})
    assert response.status_code == 200
    with app.app_context():
        device = db.session.scalar(db.select(IRZDevice).where(IRZDevice.imei == IMEI_A))
        matched_at = device.directory_matched_at
        _poll(device, monkeypatch)
        _poll(device, monkeypatch)
        db.session.refresh(device)
        assert (device.name, device.latitude, device.longitude) == ("ИП-6 (ул. Ленина)", 58.7, 49.7)
        assert device.directory_matched_at == matched_at


def test_first_match_fills_only_empty_fields_of_existing_irz(app, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device(name="ПП Чехова 8", latitude=58.5, longitude=49.5)
        _poll(device, monkeypatch)
        assert (device.name, device.latitude, device.longitude) == ("ПП Чехова 8", 58.5, 49.5)
        assert device.directory_match_status == "MATCHED"
        assert db.session.scalar(db.select(IRZMeter)).catalog_model == "Меркурий 230 ART-03 PQRSIDN"


def test_entry_without_coordinates_still_matches(app, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device()
        _poll(device, monkeypatch, serial=39807974)
        assert device.directory_match_status == "MATCHED" and device.name == "ПП-601"
        assert device.latitude is None and device.longitude is None


def test_entry_without_cabinet_keeps_default_name(app, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device()
        _poll(device, monkeypatch, serial=39163742)
        assert device.directory_match_status == "MATCHED" and device.name == f"ATM21 {IMEI_A}"


def test_manual_reapply_previews_then_overwrites(app, admin_client, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device(name="Временное", latitude=58.5, longitude=49.5)
        _poll(device, monkeypatch)
    preview = admin_client.get(f"/irz/api/devices/{IMEI_A}/directory")
    assert preview.status_code == 200
    plan = preview.get_json()
    assert {item["field"] for item in plan["changes"]} == {"name", "coordinates"} and plan["conflict"] is None
    stale = admin_client.post(f"/irz/api/devices/{IMEI_A}/directory/apply", json={"entry_id": "00000000-0000-0000-0000-000000000000"})
    assert stale.status_code == 400 and stale.get_json()["error_code"] == "DIRECTORY_PREVIEW_OUTDATED"
    applied = admin_client.post(f"/irz/api/devices/{IMEI_A}/directory/apply", json={"entry_id": plan["entry"]["id"]})
    assert applied.status_code == 200
    body = applied.get_json()
    assert body["name"] == "ИП-6" and body["location"]["latitude"] == 58.60934796
    with app.app_context():
        from app.models.audit.audit_log import AuditLog

        log = db.session.scalar(db.select(AuditLog).where(AuditLog.entity_type == "irz_device").order_by(AuditLog.created_at.desc()))
        assert "справочника ШУНО" in log.description and log.new_values["name"] == "ИП-6"


def test_manual_reapply_errors_and_permissions(app, client, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        _device()
        _device(IMEI_B)
        device_b = db.session.scalar(db.select(IRZDevice).where(IRZDevice.imei == IMEI_B))
        _poll(device_b, monkeypatch, serial=12345678)
    _login_as(app, client, "irz-dir-viewer@test.local", ["irz.view"])
    assert client.get(f"/irz/api/devices/{IMEI_A}/directory").status_code == 403
    assert client.post(f"/irz/api/devices/{IMEI_A}/directory/apply", json={}).status_code == 403
    client.post("/auth/logout")
    _login_as(app, client, "irz-dir-editor@test.local", ["irz.view", "irz.edit"])
    unknown = client.get(f"/irz/api/devices/{IMEI_A}/directory")
    assert unknown.status_code == 404 and unknown.get_json()["error_code"] == "METER_SERIAL_UNKNOWN"
    missing = client.get(f"/irz/api/devices/{IMEI_B}/directory")
    assert missing.status_code == 404 and missing.get_json()["error_code"] == "DIRECTORY_ENTRY_NOT_FOUND"


def test_same_serial_on_second_irz_is_a_conflict_not_a_silent_relink(app, admin_client, tmp_path, monkeypatch, caplog):
    with app.app_context():
        _import(tmp_path)
        first = _device(IMEI_A)
        _poll(first, monkeypatch)
        second = _device(IMEI_B)
        with caplog.at_level("WARNING", logger="app.modules.irz.cabinets"):
            _poll(second, monkeypatch)
        db.session.refresh(first)
        db.session.refresh(second)
        assert second.directory_match_status == cabinets.CONFLICT and second.directory_entry_id is None
        assert second.name == f"ATM21 {IMEI_B}" and second.latitude is None
        assert first.directory_match_status == cabinets.MATCHED and first.name == "ИП-6"
        assert "already matched" in caplog.text
        assert db.session.scalar(db.select(db.func.count(IRZMeter.id))) == 1
    detail = admin_client.get(f"/irz/api/devices/{IMEI_B}").get_json()
    assert detail["directory"]["status"] == "METER_SERIAL_CONFLICT"
    plan = admin_client.get(f"/irz/api/devices/{IMEI_B}/directory").get_json()
    assert plan["conflict"]["imei"] == IMEI_A
    assert admin_client.post(f"/irz/api/devices/{IMEI_B}/directory/apply", json={"entry_id": plan["entry"]["id"]}).status_code == 200
    with app.app_context():
        first = db.session.scalar(db.select(IRZDevice).where(IRZDevice.imei == IMEI_A))
        second = db.session.scalar(db.select(IRZDevice).where(IRZDevice.imei == IMEI_B))
        assert second.directory_match_status == "MATCHED" and second.name == "ИП-6"
        assert first.directory_entry_id is None and first.directory_match_status is None


def test_meter_replaced_after_match_is_flagged_but_not_applied(app, admin_client, tmp_path, monkeypatch):
    with app.app_context():
        _import(tmp_path)
        device = _device()
        _poll(device, monkeypatch)
        _poll(device, monkeypatch, serial=37842711)
        db.session.refresh(device)
        assert device.name == "ИП-6" and device.directory_match_serial == "40191143"
    monkeypatch.setattr(service, "get_devices", lambda: [])
    state = admin_client.get(f"/irz/api/devices/{IMEI_A}").get_json()["directory"]
    assert state["serial_changed"] is True and state["current_serial"] == "37842711"


def test_detail_page_has_directory_controls_for_editors(app, admin_client):
    with app.app_context():
        device_id = str(_device().id)
    html = admin_client.get(f"/irz/{device_id}").get_data(as_text=True)
    assert "data-directory-reapply" in html and f"/irz/api/devices/{IMEI_A}/directory" in html


def test_detail_page_hides_directory_reapply_from_viewers(app, client):
    with app.app_context():
        device_id = str(_device().id)
    _login_as(app, client, "irz-dir-reader@test.local", ["irz.view"])
    html = client.get(f"/irz/{device_id}").get_data(as_text=True)
    assert "data-directory hidden" in html and "data-directory-reapply" not in html


def test_cli_import_and_find(app, tmp_path):
    path = _workbook(tmp_path / "meters.xlsx")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["irz-import-meter-directory", "--file", str(path)])
    assert result.exit_code == 0, result.output
    for line in ("Всего строк: 6", "Добавлено: 4", "Обновлено: 0", "Пропущено: 2", "Ошибок: 0"):
        assert line in result.output
    again = runner.invoke(args=["irz-import-meter-directory", "--file", str(path)])
    assert "Добавлено: 0" in again.output and "Без изменений: 4" in again.output
    found = runner.invoke(args=["irz-meter-directory-find", "40191143"])
    assert found.exit_code == 0
    for line in ("Serial: 40191143", "ШУНО: ИП-6", "ID ШУНО: 221", "Model: Меркурий 230 ART-03 PQRSIDN",
                 "Latitude: 58.60934796", "Longitude: 49.68161881", "IRZ: не сопоставлен"):
        assert line in found.output
    assert runner.invoke(args=["irz-meter-directory-find", "99999999"]).exit_code != 0
    piped = runner.invoke(args=["irz-import-meter-directory", "--file", "-"], input=path.read_bytes())
    assert piped.exit_code == 0 and "Без изменений: 4" in piped.output
    assert runner.invoke(args=["irz-import-meter-directory", "--file", str(tmp_path / "none.xlsx")]).exit_code != 0


def test_cli_import_dry_run_writes_nothing(app, tmp_path):
    path = _workbook(tmp_path / "meters.xlsx")
    result = app.test_cli_runner().invoke(args=["irz-import-meter-directory", "--file", str(path), "--dry-run"])
    assert "Добавлено: 4" in result.output and "не сохранены" in result.output
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(MeterCabinetDirectory.id))) == 0


REAL_FILE = Path(__file__).resolve().parents[1] / "meters_with_cabinets.xlsx"


@pytest.mark.skipif(not REAL_FILE.is_file(), reason="meters_with_cabinets.xlsx is not in the working tree")
def test_real_directory_file_imports_current_rows(app):
    with app.app_context():
        report = cabinets.import_meter_directory(REAL_FILE)
        assert report["errors"] == 0 and report["total"] == report["inserted"] + report["skipped"]
        assert report["skip_reasons"].get("историческая установка (*)", 0) == report["skipped"]
        entry = cabinets.find_entry("40191143")
        assert (entry.cabinet_name, entry.cabinet_external_id, entry.meter_model) == ("ИП-6", "221", "Меркурий 230 ART-03 PQRSIDN")
        assert (entry.latitude, entry.longitude) == (58.60934796, 49.68161881)
