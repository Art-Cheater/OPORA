from cryptography.fernet import Fernet

from app.extensions import db
from datetime import timedelta
from pathlib import Path

from app.models.base import utcnow
from app.models.auth.permission import Permission
from app.models.auth.role import Role
from app.models.auth.associations import RolePermission
from app.models.devices import Device, DeviceCommand
from app.modules.auth.services import AuthService


def _login(client, email="admin@opora.ru", password="admin123"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def _device(app, key="ipp-001"):
    with app.app_context():
        app.config["DEVICE_SECRET_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        device = Device(name="Плата котельной №1", device_id=key, secret_encrypted="placeholder", connection_state="online")
        db.session.add(device)
        db.session.commit()
        return str(device.id)


def test_devices_page_is_not_empty_and_supports_partial_navigation(app, admin_client):
    response = admin_client.get("/devices/")
    assert response.status_code == 200
    assert "Удалённые платы ещё не добавлены" in response.get_data(as_text=True)
    partial = admin_client.get("/devices/", headers={"X-Opora-Nav": "1"})
    assert partial.status_code == 200
    assert "appShell" not in partial.get_data(as_text=True)
    assert "Удалённые платы" in partial.get_data(as_text=True)


def test_create_encrypts_secret_and_never_renders_it(app, admin_client):
    with app.app_context():
        app.config["DEVICE_SECRET_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    response = admin_client.post("/devices/new", data={"name": "Плата котельной №1", "device_id": "ipp-001", "secret": "plain-secret", "enabled": "y"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Плата добавлена" in response.get_data(as_text=True)
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "ipp-001"))
        assert device.secret_encrypted != "plain-secret"
    assert "plain-secret" not in response.get_data(as_text=True)


def test_duplicate_edit_secret_and_soft_delete(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        old_secret = device.secret_encrypted
    admin_client.post(f"/devices/{device_id}/edit", data={"name": "Новое имя", "device_id": "ipp-001", "secret": "", "enabled": "y"})
    with app.app_context():
        device = db.session.get(Device, device_id)
        assert device.secret_encrypted == old_secret
    admin_client.post(f"/devices/{device_id}/edit", data={"name": "Новое имя", "device_id": "ipp-001", "secret": "new-secret", "enabled": "y"})
    with app.app_context():
        device = db.session.get(Device, device_id)
        assert device.secret_encrypted != old_secret
    duplicate = admin_client.post("/devices/new", data={"name": "Дубликат", "device_id": "ipp-001", "secret": "second", "enabled": "y"})
    assert "уже существует" in duplicate.get_data(as_text=True)
    admin_client.post(f"/devices/{device_id}/delete")
    with app.app_context():
        assert db.session.get(Device, device_id).is_deleted


def test_switch_commands_are_single_relay_and_staging_guard(app, admin_client):
    device_id = _device(app)
    response = admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C6", "value": "1"})
    assert response.status_code == 302
    with app.app_context():
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.device_id == device_id))
        assert command.command_type == "switch"
        assert command.payload == {"C6": 1}
        app.config["DEVICE_COMMANDS_ENABLED"] = False
    blocked = admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C6", "value": "0"})
    assert blocked.status_code == 403


def test_switch_commands_serialize_and_keep_actual_state_unchanged(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.actual_state = {"outputs": {"C6": 0, "C7": 0, "C8": 0}}
        device.last_state_at = utcnow()
        db.session.commit()

    all_on = admin_client.post(
        f"/devices/{device_id}/commands",
        data={"action": "all_on"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert all_on.status_code == 201
    with app.app_context():
        device = db.session.get(Device, device_id)
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.device_id == device.id))
        assert command.payload == {"C6": 1, "C7": 1, "C8": 1}
        assert device.actual_state["outputs"] == {"C6": 0, "C7": 0, "C8": 0}
        assert device.desired_state["outputs"] == {"C6": 1, "C7": 1, "C8": 1}
    page = admin_client.get("/devices/")
    assert 'data-locked="1"' in page.get_data(as_text=True)

    assert admin_client.post(f"/devices/{device_id}/commands", data={"action": "all_off"}).status_code == 409
    with app.app_context():
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.device_id == device_id))
        command.status = "acknowledged"
        command.acknowledged_at = utcnow()
        command.state_confirmed_at = utcnow()
        db.session.commit()
    all_off = admin_client.post(f"/devices/{device_id}/commands", data={"action": "all_off"})
    assert all_off.status_code == 302
    with app.app_context():
        commands = db.session.scalars(db.select(DeviceCommand).order_by(DeviceCommand.created_at)).all()
        assert commands[-1].payload == {"C6": 0, "C7": 0, "C8": 0}


def test_terminal_command_statuses_release_device_queue(app, admin_client):
    for index, terminal_status in enumerate(("failed", "timeout"), start=1):
        device_id = _device(app, key=f"ipp-{index:03d}")
        assert admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C7", "value": "1"}).status_code == 302
        with app.app_context():
            first = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.device_id == device_id))
            first.status = terminal_status
            db.session.commit()
        assert admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C8", "value": "0"}).status_code == 302


def test_acknowledged_command_requires_state_confirmation_then_releases(app, admin_client):
    device_id = _device(app)
    assert admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C6", "value": "1"}).status_code == 302
    with app.app_context():
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.device_id == device_id))
        command.status = "acknowledged"
        command.acknowledged_at = utcnow()
        db.session.commit()
    blocked = admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C7", "value": "1"})
    assert blocked.status_code == 409
    with app.app_context():
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.device_id == device_id))
        command.state_confirmed_at = utcnow()
        db.session.commit()
    assert admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C7", "value": "1"}).status_code == 302


def test_state_confirmation_timeout_releases_controls_and_reports_reason(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        app.config["DEVICE_STATE_CONFIRM_TIMEOUT_SECONDS"] = 5
        device = db.session.get(Device, device_id)
        command = DeviceCommand(
            device_id=device.id,
            command_type="switch",
            payload={"C6": 1},
            status="acknowledged",
            acknowledged_at=utcnow() - timedelta(seconds=6),
        )
        db.session.add(command)
        db.session.commit()
    payload = admin_client.get("/devices/status").get_json()["devices"][0]
    assert payload["active_command"] is None
    assert payload["can_send_command"] is True
    assert payload["latest_command"]["status"] == "failed"
    assert payload["latest_command"]["error"] == "State confirmation timeout"
    assert admin_client.post(f"/devices/{device_id}/commands", data={"relay": "C7", "value": "1"}).status_code == 302


def test_devices_status_api_reports_state_telemetry_and_active_command(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.connection_state = "online"
        device.actual_state = {"outputs": {"C6": 1, "C7": 0, "C8": 1}, "inputs": {"SW2": 0}, "raw": {"G1": 1}}
        device.telemetry = {"csq": 20, "voltage": 231}
        device.last_state_at = utcnow()
        db.session.add(DeviceCommand(device_id=device.id, command_type="switch", payload={"C6": 1}))
        db.session.commit()

    response = admin_client.get("/devices/status")
    assert response.status_code == 200
    payload = response.get_json()["devices"][0]
    assert payload["actual_state"]["outputs"] == {"C6": 1, "C7": 0, "C8": 1}
    assert payload["actual_state"]["inputs"] == {"SW2": 0}
    assert payload["actual_state"]["raw"] == {"G1": 1}
    assert payload["telemetry"]["csq"] == 20
    assert payload["active_command"]["status"] == "pending"
    assert payload["can_send_command"] is False
    assert payload["command_block_reason"] == "Выполняется другая команда."


def test_status_contract_blocks_offline_and_frontend_uses_backend_decision(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.connection_state = "offline"
        db.session.commit()
    payload = admin_client.get("/devices/status").get_json()["devices"][0]
    assert {
        "device_id", "connection_state", "last_seen_at", "last_state_at", "last_ip",
        "desired_state", "actual_state", "telemetry", "active_command",
        "can_send_command", "command_block_reason",
    } <= payload.keys()
    assert payload["can_send_command"] is False
    assert payload["command_block_reason"] == "Плата OFFLINE."
    script = Path("app/static/js/devices.js").read_text(encoding="utf-8")
    assert "const locked = !device.can_send_command;" in script
    assert "waitingForState" not in script


def test_v2_completed_command_releases_status_controls(app, admin_client):
    device_id = _device(app)
    with app.app_context():
        device = db.session.get(Device, device_id)
        device.protocol_version = "2"
        db.session.add(DeviceCommand(device_id=device.id, command_type="switch", payload={"C6": 1}, status="completed", acknowledged_at=utcnow()))
        db.session.commit()
    payload = admin_client.get("/devices/status").get_json()["devices"][0]
    assert payload["active_command"] is None
    assert payload["can_send_command"] is True


def test_view_only_user_cannot_manage_devices(app, client):
    device_id = _device(app)
    with app.app_context():
        AuthService.create_user("devices-view@test.local", "pass12345", "Просмотр плат", "executor")
        role = db.session.scalar(db.select(Role).where(Role.code == "executor"))
        permission = db.session.scalar(db.select(Permission).where(Permission.code == "devices.view"))
        db.session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        db.session.commit()
    _login(client, "devices-view@test.local", "pass12345")
    page = client.get("/devices/")
    assert page.status_code == 200
    assert "Добавить плату" not in page.get_data(as_text=True)
    assert client.get("/devices/new").status_code == 403
    assert client.post("/devices/new", data={}).status_code == 403
    assert client.post(f"/devices/{device_id}/commands", data={"relay": "C6", "value": "1"}).status_code == 403
