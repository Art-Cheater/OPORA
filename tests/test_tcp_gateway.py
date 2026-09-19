import asyncio

from cryptography.fernet import Fernet

from app.extensions import db
from app.models.devices import Device, DeviceCommand
from app.tcp_gateway.main import Gateway
from app.tcp_gateway.protocol import calculate_hmac, decode_frame, encode_frame, hmac_matches, new_nonce
from app.tcp_gateway.secrets import encrypt_device_secret


class _GatewayWriter:
    def __init__(self):
        self.frames: list[dict] = []
        self.closed = False

    def get_extra_info(self, name):
        return ("127.0.0.1", 45678) if name == "peername" else None

    def write(self, data):
        self.frames.append(decode_frame(data, 8192))

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


async def _authenticate(gateway, device_id: str, secret: str):
    reader = asyncio.StreamReader()
    writer = _GatewayWriter()
    task = asyncio.create_task(gateway.handle_connection(reader, writer))
    while not writer.frames:
        await asyncio.sleep(0)
    challenge = writer.frames[0]
    reader.feed_data(
        encode_frame(
            {
                "type": "auth",
                "version": gateway.app.config["DEVICE_PROTOCOL_VERSION"],
                "device_id": device_id,
                "hmac": calculate_hmac(secret, device_id, challenge["nonce"]),
            }
        )
    )
    reader.feed_eof()
    await task
    return writer.frames


def _gateway_device(app, *, device_id="board-01", enabled=True, secret="shared-secret"):
    with app.app_context():
        app.config["DEVICE_SECRET_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        device = Device(
            device_id=device_id,
            name="Test board",
            secret_encrypted=encrypt_device_secret(secret),
            enabled=enabled,
        )
        db.session.add(device)
        db.session.commit()
    return secret


def test_gateway_hmac_is_nonce_bound():
    nonce = new_nonce()
    signature = calculate_hmac("shared-secret", "board-01", nonce)
    assert hmac_matches("shared-secret", "board-01", nonce, signature)
    assert not hmac_matches("shared-secret", "board-01", "another-nonce", signature)


def test_gateway_rejects_invalid_or_oversize_frame():
    assert decode_frame(encode_frame({"type": "pong"}), 1024) == {"type": "pong"}
    for raw in (b"not-json\n", b'{"x": 1}\n', b"x" * 32):
        try:
            decode_frame(raw, 16)
        except ValueError:
            pass
        else:
            raise AssertionError("bad frame was accepted")


def test_device_command_is_durable_and_starts_pending(app):
    with app.app_context():
        device = Device(device_id="board-01", name="Test board", secret_encrypted="encrypted")
        db.session.add(device)
        db.session.flush()
        command = DeviceCommand(device_id=device.id, command_type="set_output", payload={"C6": 1})
        db.session.add(command)
        db.session.commit()
        saved = db.session.get(DeviceCommand, command.id)
        assert saved.status == "pending"
        assert saved.command_id


def test_gateway_authentication_decrypts_secret_inside_application_context(app):
    secret = _gateway_device(app)
    frames = asyncio.run(_authenticate(Gateway(app), "board-01", secret))
    assert [frame["type"] for frame in frames] == ["challenge", "authenticated"]


def test_gateway_rejects_unknown_disabled_and_invalid_hmac_devices(app):
    secret = _gateway_device(app, enabled=False)
    assert [frame["type"] for frame in asyncio.run(_authenticate(Gateway(app), "board-01", secret))] == ["challenge"]

    _gateway_device(app, device_id="board-02", secret="other-secret")
    assert [frame["type"] for frame in asyncio.run(_authenticate(Gateway(app), "unknown", secret))] == ["challenge"]
    assert [frame["type"] for frame in asyncio.run(_authenticate(Gateway(app), "board-02", secret))] == ["challenge"]


def test_gateway_state_is_the_only_actual_source_and_confirms_acknowledged_command(app):
    secret = _gateway_device(app)
    gateway = Gateway(app)
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        device.actual_state = {"outputs": {"C6": 0}}
        command = DeviceCommand(device_id=device.id, command_type="switch", payload={"C6": 1}, status="sent")
        db.session.add(command)
        db.session.commit()
        command_id = command.command_id

    gateway._ack("board-01", command_id, True, "")
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.command_id == command_id))
        assert command.status == "acknowledged"
        assert command.state_confirmed_at is None
        assert device.actual_state == {"outputs": {"C6": 0}}

    gateway._set_connection(
        "board-01",
        "online",
        actual={"C6": 1, "phases": {"A": 1, "B": 0, "C": 1}, "inputs": {"door": 0}},
        telemetry={"csq": 20},
    )
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.command_id == command_id))
        assert device.actual_state == {"outputs": {"C6": 1}, "phases": {"A": 1, "B": 0, "C": 1}, "inputs": {"door": 0}}
        assert device.telemetry == {"csq": 20}
        assert device.last_state_at is not None
        assert command.state_confirmed_at is not None
