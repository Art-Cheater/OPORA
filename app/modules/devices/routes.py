"""Administrative UI and durable command queue for device controllers."""
from __future__ import annotations

import uuid
from collections import defaultdict

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.audit_service import AuditService
from app.core.decorators import permission_required
from app.extensions import db
from app.models.devices import Device, DeviceCommand
from app.modules.devices.blueprint import devices_bp
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


@devices_bp.route("/")
@login_required
@permission_required("devices.view")
def index():
    devices = db.session.scalars(db.select(Device).where(Device.active_filter()).order_by(Device.name)).all()
    return render_template("devices/index.html", devices=devices, commands_by_device=_commands_by_device(devices))


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
    device = _device_or_404(device_id)
    relay, value = (request.form.get("relay") or "").upper(), request.form.get("value")
    if not device.enabled:
        flash("Нельзя отправить команду деактивированной плате.", "danger")
    elif relay not in {"C6", "C7", "C8"} or value not in {"0", "1"}:
        abort(400)
    else:
        command = DeviceCommand(device_id=device.id, command_type="switch", payload={relay: int(value)}, created_by=current_user.id)
        db.session.add(command)
        db.session.flush()
        AuditService.log(user_id=current_user.id, action="update", entity_type="device", entity_id=device.id, description=f"Поставлена команда переключения {relay} для {device.device_id}")
        db.session.commit()
        flash("Команда поставлена в очередь и ожидает ACK устройства.", "success")
    return redirect(url_for("devices.index"))
