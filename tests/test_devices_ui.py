from cryptography.fernet import Fernet

from app.extensions import db
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
        device = Device(name="Плата котельной №1", device_id=key, secret_encrypted="placeholder")
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
