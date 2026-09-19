"""Administrative UI and durable command queue for device controllers."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.audit_service import AuditService
from app.core.decorators import permission_required
from app.extensions import db
from app.models.base import as_utc_aware, utcnow
from app.models.devices import Device, DeviceCommand
from app.models.devices.state import OUTPUT_RELAYS, normalize_actual_state, payload_matches_actual
from app.modules.devices.blueprint import devices_bp
from app.modules.devices.command_service import active_command_query, expire_state_confirmation_timeouts
from app.modules.devices.forms import DeviceForm
from app.tcp_gateway.secrets import encrypt_device_secret


def _device_or_404(device_id: uuid.UUID) -> Device:
    device = db.session.get(Device, device_id)
    if device is None or device.is_deleted:
        abort(404)
    return device


def _commands_by_device(devices: list[Device]) -> dict[uuid.UUID, list[DeviceCommand]]:
    if not devices:
        return {}
    commands = db.session.scalars(db.select(DeviceCommand).where(DeviceCommand.device_id.in_([item.id for item in devices])).order_by(DeviceCommand.created_at.desc())).all()
    result: dict[uuid.UUID, list[DeviceCommand]] = defaultdict(list)
    for command in commands:
        if len(result[command.device_id]) < 5:
            result[command.device_id].append(command)
    return result


def _active_commands_by_device(devices: list[Device]) -> dict[uuid.UUID, DeviceCommand]:
    if not devices:
        return {}
    commands = db.session.scalars(
        db.select(DeviceCommand).where(
            DeviceCommand.device_id.in_([item.id for item in devices]),
            or_(
                DeviceCommand.status.in_(("pending", "sent")),
                and_(DeviceCommand.status == "acknowledged", DeviceCommand.state_confirmed_at.is_(None)),
            ),
            DeviceCommand.active_filter(),
        )
    ).all()
    return {command.device_id: command for command in commands}


def _serialize_datetime(value):
    return value.isoformat() if value else None


def _serialize_command(command: DeviceCommand | None, device: Device) -> dict | None:
    if command is None:
        return None
    confirmation = None
    if command.status == "acknowledged":
        if command.state_confirmed_at:
            confirmation = "confirmed"
        elif device.last_state_at and not payload_matches_actual(command.payload, device.actual_state):
            confirmation = "mismatch"
        else:
            confirmation = "waiting_state"
    return {
        "command_id": command.command_id,
        "command_type": command.command_type,
        "payload": command.payload or {},
        "status": command.status,
        "created_at": _serialize_datetime(command.created_at),
        "sent_at": _serialize_datetime(command.sent_at),
        "acknowledged_at": _serialize_datetime(command.acknowledged_at),
        "state_confirmed_at": _serialize_datetime(command.state_confirmed_at),
        "failed_at": _serialize_datetime(command.failed_at),
        "error": command.error,
        "confirmation": confirmation,
    }


def _serialize_device(device: Device, active_command: DeviceCommand | None, latest_command: DeviceCommand | None) -> dict:
    now = utcnow()
    last_state = as_utc_aware(device.last_state_at)
    stale_after = timedelta(seconds=current_app.config["DEVICE_STATE_STALE_SECONDS"])
    state_stale = device.connection_state != "online" or last_state is None or now - last_state > stale_after
    actual = normalize_actual_state(device.actual_state)
    commands_enabled = bool(current_app.config.get("DEVICE_COMMANDS_ENABLED"))
    if not commands_enabled:
        block_reason = "Отправка команд отключена в этом окружении."
    elif not device.enabled:
        block_reason = "Плата деактивирована."
    elif device.connection_state != "online":
        block_reason = "Плата OFFLINE."
    elif active_command is not None:
        block_reason = (
            "Ожидание подтверждающего state от платы."
            if active_command.status == "acknowledged"
            else "Выполняется другая команда."
        )
    else:
        block_reason = None
    return {
        "device_id": str(device.id),
        "external_device_id": device.device_id,
        "connection_state": device.connection_state,
        "last_seen_at": _serialize_datetime(device.last_seen_at),
        "last_state_at": _serialize_datetime(device.last_state_at),
        "last_ip": device.last_ip,
        "actual_state": actual,
        "desired_state": normalize_actual_state(device.desired_state),
        "telemetry": device.telemetry or {},
        "state_stale": state_stale,
        "active_command": _serialize_command(active_command, device),
        "latest_command": _serialize_command(latest_command, device),
        "can_send_command": block_reason is None,
        "command_block_reason": block_reason,
    }


def _switch_payload_from_form() -> dict[str, int]:
    action = request.form.get("action")
    if action == "all_on":
        return {relay: 1 for relay in OUTPUT_RELAYS}
    if action == "all_off":
        return {relay: 0 for relay in OUTPUT_RELAYS}
    relay, value = (request.form.get("relay") or "").upper(), request.form.get("value")
    if relay not in OUTPUT_RELAYS or value not in {"0", "1"}:
        abort(400)
    return {relay: int(value)}


def _queue_switch_command(device_id: uuid.UUID, payload: dict[str, int]) -> DeviceCommand:
    """Serialize commands per device with a row lock and database invariant."""
    device = db.session.scalar(
        db.select(Device).where(Device.id == device_id, Device.active_filter()).with_for_update()
    )
    if device is None:
        abort(404)
    if not device.enabled:
        abort(409, description="Плата деактивирована.")
    if device.connection_state != "online":
        abort(409, description="Плата OFFLINE.")
    expire_state_confirmation_timeouts(device_id=device.id)
    active = db.session.scalar(active_command_query(device.id))
    if active:
        abort(409, description="Для этой платы уже выполняется команда.")

    desired = dict(device.desired_state or {})
    desired_outputs = normalize_actual_state(desired).get("outputs", {})
    desired_outputs.update(payload)
    desired["outputs"] = desired_outputs
    device.desired_state = desired
    command = DeviceCommand(
        device_id=device.id,
        command_type="switch",
        payload=payload,
        created_by=current_user.id,
    )
    db.session.add(command)
    db.session.flush()
    AuditService.log(
        user_id=current_user.id,
        action="update",
        entity_type="device",
        entity_id=device.id,
        description=f"Поставлена команда переключения для {device.device_id}",
    )
    return command


@devices_bp.route("/")
@login_required
@permission_required("devices.view")
def index():
    if expire_state_confirmation_timeouts():
        db.session.commit()
    devices = db.session.scalars(db.select(Device).where(Device.active_filter()).order_by(Device.name)).all()
    commands_by_device = _commands_by_device(devices)
    active_by_device = _active_commands_by_device(devices)
    status_by_device = {
        device.id: _serialize_device(
            device,
            active_by_device.get(device.id),
            commands_by_device.get(device.id, [None])[0],
        )
        for device in devices
    }
    return render_template(
        "devices/index.html",
        devices=devices,
        commands_by_device=commands_by_device,
        status_by_device=status_by_device,
    )


@devices_bp.route("/status")
@login_required
@permission_required("devices.view")
def status():
    if expire_state_confirmation_timeouts():
        db.session.commit()
    devices = db.session.scalars(db.select(Device).where(Device.active_filter()).order_by(Device.name)).all()
    commands_by_device = _commands_by_device(devices)
    active_by_device = _active_commands_by_device(devices)
    return jsonify(
        {
            "commands_enabled": bool(current_app.config.get("DEVICE_COMMANDS_ENABLED")),
            "devices": [
                _serialize_device(
                    device,
                    active_by_device.get(device.id),
                    commands_by_device.get(device.id, [None])[0],
                )
                for device in devices
            ],
        }
    )


@devices_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("devices.manage")
def create():
    form = DeviceForm()
    if form.validate_on_submit():
        key = form.device_id.data.strip()
        duplicate = db.session.scalar(db.select(Device.id).where(Device.device_id == key, Device.active_filter()))
        if duplicate:
            form.device_id.errors.append("Плата с таким Device ID уже существует.")
        else:
            try:
                device = Device(name=form.name.data.strip(), device_id=key, secret_encrypted=encrypt_device_secret(form.secret.data.strip()), enabled=bool(form.enabled.data), connection_state="offline", created_by=current_user.id)
            except (RuntimeError, ValueError):
                flash("Не удалось безопасно сохранить секрет платы. Проверьте настройку gateway.", "danger")
            else:
                db.session.add(device)
                db.session.flush()
                AuditService.log(user_id=current_user.id, action="create", entity_type="device", entity_id=device.id, description=f"Добавлена плата {device.device_id}")
                db.session.commit()
                flash("Плата добавлена.", "success")
                return redirect(url_for("devices.index"))
    return render_template("devices/form.html", form=form, device=None)


@devices_bp.route("/<uuid:device_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("devices.manage")
def edit(device_id):
    device = _device_or_404(device_id)
    form = DeviceForm(obj=device)
    form.is_edit = True
    if request.method == "GET":
        form.device_id.data, form.name.data, form.enabled.data = device.device_id, device.name, device.enabled
    if form.validate_on_submit():
        key = form.device_id.data.strip()
        duplicate = db.session.scalar(db.select(Device.id).where(Device.device_id == key, Device.id != device.id, Device.active_filter()))
        if duplicate:
            form.device_id.errors.append("Плата с таким Device ID уже существует.")
        else:
            try:
                if (form.secret.data or "").strip():
                    device.secret_encrypted = encrypt_device_secret(form.secret.data.strip())
                device.name, device.device_id, device.enabled, device.updated_by = form.name.data.strip(), key, bool(form.enabled.data), current_user.id
                AuditService.log(user_id=current_user.id, action="update", entity_type="device", entity_id=device.id, description=f"Изменена плата {device.device_id}")
                db.session.commit()
            except (RuntimeError, ValueError):
                db.session.rollback()
                flash("Не удалось безопасно сохранить секрет платы. Проверьте настройку gateway.", "danger")
            else:
                flash("Плата сохранена.", "success")
                return redirect(url_for("devices.index"))
    return render_template("devices/form.html", form=form, device=device)


@devices_bp.route("/<uuid:device_id>/delete", methods=["POST"])
@login_required
@permission_required("devices.manage")
def delete(device_id):
    device = _device_or_404(device_id)
    device.enabled, device.connection_state = False, "offline"
    device.soft_delete(current_user.id)
    AuditService.log(user_id=current_user.id, action="soft_delete", entity_type="device", entity_id=device.id, description=f"Удалена плата {device.device_id}")
    db.session.commit()
    flash("Плата деактивирована и удалена из списка.", "success")
    return redirect(url_for("devices.index"))


@devices_bp.route("/<uuid:device_id>/commands", methods=["POST"])
@login_required
@permission_required("devices.manage")
def create_command(device_id):
    if not current_app.config.get("DEVICE_COMMANDS_ENABLED"):
        abort(403)
    payload = _switch_payload_from_form()
    try:
        command = _queue_switch_command(device_id, payload)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, description="Для этой платы уже выполняется команда.")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"command_id": command.command_id, "status": command.status}), 201
    flash("Команда поставлена в очередь и ожидает плату.", "success")
    return redirect(url_for("devices.index"))
