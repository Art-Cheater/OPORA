"""IRZ Console page and browser-facing JSON API."""

import csv
import io

from flask import Response, jsonify, render_template, request
from flask_login import current_user, login_required

from app.core.audit_service import AuditService
from app.core.decorators import permission_required
from app.extensions import db
from app.modules.irz import service
from app.modules.irz.blueprint import irz_bp


@irz_bp.get("")
@login_required
@permission_required("irz.view")
def index():
    return render_template("irz/index.html", can_send=current_user.has_permission("irz.send"))


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
