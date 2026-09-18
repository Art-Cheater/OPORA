"""Admin UI and durable command queue for device controllers."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.core.audit_service import AuditService
from app.core.decorators import permission_required
from app.extensions import db
from app.models.devices import Device, DeviceCommand
from app.modules.devices.blueprint import devices_bp


@devices_bp.route("/")
@login_required
@permission_required("devices.view")
def index():
    devices = db.session.scalars(db.select(Device).where(Device.active_filter()).order_by(Device.name)).all()
    return render_template("devices/index.html", devices=devices)


@devices_bp.route("/<uuid:device_id>/commands", methods=["POST"])
@login_required
@permission_required("devices.manage")
def create_command(device_id):
    device = db.session.get(Device, device_id)
    if device is None or device.is_deleted:
        abort(404)
    command_type = (request.form.get("command_type") or "").strip()
    if not command_type or len(command_type) > 64:
        flash("Укажите допустимый тип команды.", "danger")
        return redirect(url_for("devices.index"))
    command = DeviceCommand(device_id=device.id, command_type=command_type, payload={}, created_by=current_user.id)
    db.session.add(command)
    db.session.flush()
    AuditService.log(user_id=current_user.id, action="device_command", entity_type="device", entity_id=device.id, description=f"Создана команда {command.command_id} для {device.device_id}")
    db.session.commit()
    flash("Команда поставлена в очередь и ожидает ACK устройства.", "success")
    return redirect(url_for("devices.index"))
