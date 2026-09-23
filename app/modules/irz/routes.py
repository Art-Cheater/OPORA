"""IRZ monitoring pages (map, device detail, wall display) and JSON API."""

import csv
import io
from datetime import datetime, timezone

from flask import Response, abort, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.audit_service import AuditService
from app.core.decorators import any_permission_required, permission_required
from app.extensions import db
from app.models.irz import IRZMeter
from app.modules.irz import directory, service
from app.modules.irz.blueprint import irz_bp


@irz_bp.get("")
@login_required
@permission_required("irz.view")
def index():
    return render_template(
        "irz/index.html",
        can_edit=current_user.has_permission("irz.edit"),
        can_map_display=current_user.has_permission("irz.map_display"),
    )


@irz_bp.get("/map-display")
@login_required
@permission_required("irz.map_display")
def map_display():
    return render_template(
        "irz/map_display.html",
        can_open_detail=current_user.has_permission("irz.view"),
        refresh_seconds=min(max(int(current_app.config.get("IRZ_MAP_DISPLAY_REFRESH_SECONDS", 20)), 15), 30),
    )


@irz_bp.get("/<device_ref>")
@login_required
@permission_required("irz.view")
def device_page(device_ref):
    try:
        device = service.get_device_by_imei(device_ref) if device_ref.isdigit() else service.get_device(device_ref)
    except (ValueError, LookupError):
        abort(404)
    if device_ref != str(device.id):
        return redirect(url_for("irz.device_page", device_ref=str(device.id)))
    return render_template(
        "irz/device.html",
        device=device,
        title=directory.custom_name(device) or directory.default_name(device.imei),
        can_edit=current_user.has_permission("irz.edit"),
        can_poll=current_user.has_permission("irz.poll"),
    )


def _directory_payload():
    live, gateway_ok = directory.live_sessions()
    items = directory.build_directory(live, gateway_ok)
    return items, {
        "counters": directory.counters(items),
        "gateway": "online" if gateway_ok else "unavailable",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fresh_seconds": int(current_app.config.get("IRZ_DATA_FRESH_SECONDS", 900)),
    }


@irz_bp.get("/api/map")
@login_required
@any_permission_required("irz.view", "irz.map_display")
def map_summary():
    """Light marker payload for the map and the wall display; counters cover every device."""
    items, meta = _directory_payload()
    try:
        selected = directory.filter_items(items, query=request.args.get("q", ""),
                                          status=request.args.get("status", "all"), has_coordinates=True)
        from app.core.geo.bbox import BboxError, filter_records, parse_bbox

        bbox = parse_bbox(request.args)
    except BboxError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except ValueError as exc:
        return _error_response(exc)
    if bbox:
        selected = filter_records(selected, bbox)
    return jsonify({**meta, "items": selected})


@irz_bp.get("/api/directory")
@login_required
@permission_required("irz.view")
def directory_list():
    items, meta = _directory_payload()
    try:
        selected = directory.filter_items(
            items, query=request.args.get("q", ""), status=request.args.get("status", "all"),
            has_coordinates=directory.parse_bool(request.args.get("has_coordinates")),
        )
    except ValueError as exc:
        return _error_response(exc)
    page_items, pagination = directory.paginate(
        selected, request.args.get("page", 1, type=int),
        request.args.get("per_page", directory.MAX_PER_PAGE, type=int),
    )
    return jsonify({**meta, "items": page_items, "pagination": pagination})


@irz_bp.get("/api/devices")
@login_required
@permission_required("irz.view")
def devices():
    try:
        items = service.get_devices()
    except (service.GatewayUnavailable, service.GatewayResponseError):
        return jsonify({"status": "offline", "devices": []}), 503
    return jsonify({"status": "online", "devices": items})


@irz_bp.get("/api/logs")
@login_required
@permission_required("irz.view")
def logs():
    limit = min(max(request.args.get("limit", 200, type=int), 1), 200)
    imei = (request.args.get("imei") or "").strip() or None
    return jsonify(
        [
            {
                "id": str(item.id),
                "created_at": item.created_at.isoformat(),
                "imei": item.imei,
                "direction": item.direction,
                "hex": item.raw_hex,
                "ascii": item.raw_ascii,
                "length": item.raw_length,
                "packet_type": item.packet_type,
            }
            for item in service.recent_logs(limit=limit, imei=imei)
        ]
    )


@irz_bp.get("/api/experiments")
@login_required
@permission_required("irz.view")
def experiments():
    imei = (request.args.get("imei") or "").strip() or None
    return jsonify(
        [
            {
                "id": str(item.id),
                "created_at": item.created_at.isoformat(),
                "imei": item.imei,
                "command_hex": item.command_hex,
                "response_hex": item.response_hex,
                "response_ascii": item.response_ascii,
                "success": item.success,
            }
            for item in service.recent_experiments(limit=50, imei=imei)
        ]
    )


@irz_bp.get("/api/export")
@login_required
@permission_required("irz.view")
def export_session():
    imei = (request.args.get("imei") or "").strip() or None
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["time", "direction", "hex", "ascii"])
    for item in service.all_logs(imei=imei):
        writer.writerow([item.created_at.isoformat(), item.direction, item.raw_hex, item.raw_ascii])
    filename = f"irz-session-{imei or 'all'}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@irz_bp.post("/api/send")
@login_required
@permission_required("irz.send")
def send():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid request"}), 400
    try:
        result = service.send_command(payload.get("imei"), payload.get("hex"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except service.GatewayResponseError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    except service.GatewayUnavailable:
        return jsonify({"error": "gateway unavailable"}), 503
    AuditService.log(
        user_id=current_user.id,
        action="update",
        entity_type="irz",
        description=f"Отправлена IRZ HEX-команда устройству {payload['imei']}",
        new_values={"imei": payload["imei"], "bytes": result.get("bytes")},
    )
    db.session.commit()
    return jsonify(result)


@irz_bp.post("/api/test-command")
@login_required
@permission_required("irz.send")
def test_command():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid request"}), 400
    try:
        experiment = service.run_experiment(
            payload.get("imei"),
            payload.get("hex"),
            crc=payload.get("crc", "none"),
            append=payload.get("append", "none"),
            user_id=current_user.id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except service.GatewayResponseError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    except service.GatewayUnavailable:
        return jsonify({"error": "gateway unavailable"}), 503
    AuditService.log(
        user_id=current_user.id,
        action="update",
        entity_type="irz",
        description=f"Выполнен IRZ protocol test для {experiment.imei}",
        new_values={"imei": experiment.imei, "success": experiment.success},
    )
    db.session.commit()
    return jsonify(
        {
            "id": str(experiment.id),
            "command_hex": experiment.command_hex,
            "response_hex": experiment.response_hex,
            "response_ascii": experiment.response_ascii,
            "success": experiment.success,
        }
    )


def _error_response(exc):
    if isinstance(exc, KeyError):
        return jsonify({"success": False, "error_code": "INVALID_COMMAND", "message": "Неизвестная команда"}), 404
    if isinstance(exc, ValueError):
        return jsonify({"success": False, "error_code": str(exc), "message": str(exc)}), 400
    if isinstance(exc, LookupError):
        return jsonify({"success": False, "error_code": "DEVICE_NOT_FOUND", "message": str(exc)}), 404
    if isinstance(exc, service.GatewayResponseError):
        return jsonify({"success": False, "error_code": exc.error_code, "message": str(exc)}), exc.status_code
    return jsonify({"success": False, "error_code": "CONNECTION_ERROR", "message": "Шлюз связи недоступен"}), 503


@irz_bp.get("/api/mercury/devices")
@login_required
@permission_required("irz.view")
def mercury_devices():
    try:
        items, online, runtime = service.list_mercury_devices()
    except (service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)
    return jsonify([service.serialize_device(item, online=item.imei in online, runtime=runtime.get(item.imei, {})) for item in items])


def _monitoring_device(imei):
    device = service.get_device_by_imei(imei)
    try:
        live = {item["imei"]: item for item in service.get_devices() if item.get("imei")}
    except (service.GatewayUnavailable, service.GatewayResponseError):
        live = {}
    return device, live


@irz_bp.get("/api/devices/<imei>")
@login_required
@permission_required("irz.view")
def monitoring_device_detail(imei):
    try:
        device, live = _monitoring_device(imei)
        return jsonify(service.serialize_device(device, online=imei in live, runtime=live.get(imei, {})))
    except (ValueError, LookupError) as exc:
        return _error_response(exc)


@irz_bp.patch("/api/devices/<imei>")
@login_required
@permission_required("irz.edit")
def monitoring_device_update(imei):
    try:
        device = service.get_device_by_imei(imei)
        payload = request.get_json(silent=True) or {}
        service.update_device_profile(device, payload, user_id=current_user.id)
    except (ValueError, LookupError) as exc:
        return _error_response(exc)
    AuditService.log(user_id=current_user.id, action="update", entity_type="irz_device", entity_id=device.id,
                     description=f"Обновлена карточка IRZ {imei}", new_values={key: payload.get(key) for key in ("name", "latitude", "longitude", "address_text") if key in payload})
    db.session.commit()
    return jsonify(service.serialize_device(device))


@irz_bp.get("/api/devices/<imei>/latest")
@login_required
@permission_required("irz.view")
def monitoring_latest(imei):
    try:
        device = service.get_device_by_imei(imei)
        meter = db.session.scalar(db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id))
        snapshot = service.latest_meter_snapshot(meter) if meter else None
        return jsonify(service.serialize_snapshot(snapshot, include_delta=True) if snapshot else None)
    except (ValueError, LookupError) as exc:
        return _error_response(exc)


@irz_bp.get("/api/devices/<imei>/snapshots")
@login_required
@permission_required("irz.view")
def monitoring_snapshots(imei):
    try:
        device = service.get_device_by_imei(imei)
        meter = db.session.scalar(db.select(IRZMeter).where(IRZMeter.active_filter(), IRZMeter.irz_device_id == device.id))
        limit = request.args.get("limit", 30, type=int)
        return jsonify([service.serialize_snapshot(item) for item in service.meter_snapshots(meter, limit=limit)] if meter else [])
    except (ValueError, LookupError) as exc:
        return _error_response(exc)


@irz_bp.post("/api/devices/<imei>/poll")
@login_required
@permission_required("irz.poll")
def monitoring_poll(imei):
    try:
        device = service.get_device_by_imei(imei)
        result = service.poll_device(device, user_id=current_user.id, source="MANUAL")
        return jsonify(result)
    except (ValueError, LookupError, service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)


@irz_bp.post("/api/devices/<imei>/events")
@login_required
@permission_required("irz.poll")
def monitoring_events(imei):
    try:
        device = service.get_device_by_imei(imei)
        return jsonify(service.execute_device_command(device, "events", user_id=current_user.id))
    except (ValueError, LookupError, service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)


@irz_bp.post("/api/devices/<imei>/energy-archive")
@login_required
@permission_required("irz.poll")
def monitoring_energy_archive(imei):
    try:
        device = service.get_device_by_imei(imei)
        params = service.energy_archive_params(request.get_json(silent=True) or {})
        return jsonify(service.execute_device_command(device, "energy_archive", user_id=current_user.id, params=params))
    except (ValueError, LookupError, service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)


@irz_bp.get("/api/mercury/devices/<device_id>")
@login_required
@permission_required("irz.view")
def mercury_device_detail(device_id):
    try:
        device = service.get_device(device_id)
        live = {item["imei"]: item for item in service.get_devices()}
        return jsonify(service.serialize_device(device, online=device.imei in live, runtime=live.get(device.imei, {})))
    except (ValueError, LookupError, service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)


@irz_bp.patch("/api/mercury/devices/<device_id>")
@login_required
@permission_required("irz.control")
def mercury_device_update(device_id):
    try:
        device = service.get_device(device_id)
        payload = request.get_json(silent=True) or {}
        service.set_network_address(device, payload.get("network_address"))
    except (ValueError, LookupError) as exc:
        return _error_response(exc)
    AuditService.log(user_id=current_user.id, action="update", entity_type="irz_device", entity_id=device.id,
                     description=f"Изменён сетевой адрес Mercury за ATM21 {device.imei}", new_values={"network_address": device.network_address})
    db.session.commit()
    return jsonify(service.serialize_device(device))


@irz_bp.patch("/api/mercury/devices/<device_id>/identity")
@login_required
@permission_required("irz.edit")
def mercury_device_identity(device_id):
    try:
        device = service.get_device(device_id)
        payload = request.get_json(silent=True) or {}
        old_name = device.name
        service.rename_device(device, payload.get("name"), user_id=current_user.id)
    except (ValueError, LookupError) as exc:
        return _error_response(exc)
    AuditService.log(user_id=current_user.id, action="update", entity_type="irz_device", entity_id=device.id,
                     description=f"Переименован IRZ {device.imei}", old_values={"name": old_name},
                     new_values={"name": device.name})
    db.session.commit()
    return jsonify(service.serialize_device(device))


@irz_bp.patch("/api/mercury/devices/<device_id>/meter")
@login_required
@permission_required("irz.admin")
def mercury_meter_identity(device_id):
    try:
        device = service.get_device(device_id)
        payload = request.get_json(silent=True) or {}
        meter = service.update_meter_identity(device, payload, user_id=current_user.id)
    except (ValueError, LookupError) as exc:
        return _error_response(exc)
    AuditService.log(user_id=current_user.id, action="update", entity_type="irz_meter", entity_id=meter.id,
                     description=f"Изменены реквизиты Mercury {meter.serial_number}",
                     new_values={"custom_name": meter.custom_name, "model": meter.model})
    db.session.commit()
    return jsonify(service.serialize_meter(meter))


@irz_bp.post("/api/mercury/devices/<device_id>/test")
@login_required
@permission_required("irz.poll")
def mercury_test(device_id):
    try:
        device = service.get_device(device_id)
        result = service.execute_device_command(device, "serial_and_manufacture", user_id=current_user.id, operation="TEST")
    except (ValueError, LookupError, service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)
    return jsonify(result)


@irz_bp.get("/api/mercury/devices/<device_id>/commands")
@login_required
@permission_required("irz.view")
def mercury_commands(device_id):
    try:
        service.get_device(device_id)
    except (ValueError, LookupError) as exc:
        return _error_response(exc)
    return jsonify(service.command_list(include_unavailable=False))


@irz_bp.post("/api/mercury/devices/<device_id>/commands/<command_id>")
@login_required
@permission_required("irz.poll")
def mercury_command(device_id, command_id):
    try:
        command = service.get_command(command_id)
        required = "irz.control" if command.mode != "read" or command.dangerous else "irz.poll"
        if not current_user.has_permission(required):
            return jsonify({"success": False, "error_code": "PERMISSION_DENIED", "message": "Недостаточно прав"}), 403
        payload = request.get_json(silent=True) or {}
        if command.dangerous and payload.get("confirm") is not True:
            return jsonify({"success": False, "error_code": "CONFIRMATION_REQUIRED", "message": "Требуется подтверждение опасной команды"}), 409
        device = service.get_device(device_id)
        raw_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        params = service.energy_archive_params(raw_params) if command.id == "energy_archive" else None
        result = service.execute_device_command(device, command_id, user_id=current_user.id, params=params)
    except (KeyError, ValueError, LookupError, service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)
    AuditService.log(user_id=current_user.id, action="update", entity_type="irz_device", entity_id=device.id, description=f"IRZ команда {command.id}: {device.name}", new_values={"command": command.id})
    db.session.commit()
    return jsonify(result)


@irz_bp.post("/api/mercury/devices/<device_id>/poll")
@login_required
@permission_required("irz.poll")
def mercury_poll(device_id):
    try:
        device = service.get_device(device_id)
        result = service.poll_device(device, user_id=current_user.id)
    except (ValueError, LookupError, service.GatewayUnavailable, service.GatewayResponseError) as exc:
        return _error_response(exc)
    AuditService.log(user_id=current_user.id, action="update", entity_type="irz_device", entity_id=device.id, description=f"Комплексный опрос Mercury: {device.name}", new_values={"partial": result.get("partial")})
    db.session.commit()
    return jsonify(result)


@irz_bp.get("/api/mercury/devices/<device_id>/exchange-log")
@login_required
@permission_required("irz.view")
def mercury_exchange_log(device_id):
    try:
        device = service.get_device(device_id)
    except (ValueError, LookupError) as exc:
        return _error_response(exc)
    limit = min(max(request.args.get("limit", 100, type=int), 1), 200)
    status = request.args.get("status")
    items = service.operation_logs(device, limit=limit, status=status)
    structured = [
        {
            "id": str(item.id), "created_at": item.created_at.isoformat(), "command_id": item.command_id,
            "mercury_command": item.mercury_command, "operation": item.operation, "status": item.status,
            "result": item.result, "error_code": item.error_code, "error_message": item.error_message,
            "duration_ms": item.duration_ms, "tx_raw": item.tx_raw, "rx_raw": item.rx_raw,
            "crc_ok": True if item.status == "SUCCESS" and item.rx_raw else (False if item.error_code == "CRC_ERROR" else None),
        }
        for item in items
    ]
    if not status:
        for item in service.recent_logs(limit=limit, imei=device.imei):
            structured.append({"id": str(item.id), "created_at": item.created_at.isoformat(),
                               "command_id": item.packet_type or "UNKNOWN_RAW", "operation": item.direction,
                               "status": "SUCCESS", "result": item.raw_ascii, "error_code": None,
                               "error_message": None, "duration_ms": None,
                               "tx_raw": item.raw_hex if item.direction == "TX" else None,
                               "rx_raw": item.raw_hex if item.direction == "RX" else None, "crc_ok": None})
    structured.sort(key=lambda item: item["created_at"], reverse=True)
    return jsonify(structured[:limit])
