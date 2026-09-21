import asyncio
import json

from cryptography.fernet import Fernet

from app.extensions import db
from app.models.devices import Device, DeviceCommand, DeviceDiagnosticSample
from app.tcp_gateway.main import Gateway
from app.tcp_gateway.protocol import calculate_hmac, decode_frame, decode_v2_frame, encode_frame, encode_v2_frame, hmac_matches, new_nonce, parse_v2_state
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

    def is_closing(self):
        return self.closed

    async def wait_closed(self):
        return None


class _TextGatewayWriter(_GatewayWriter):
    def write(self, data):
        self.frames.append(data.decode("ascii").strip())


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


async def _authenticate_v2(gateway, device_id: str, secret: str):
    reader = asyncio.StreamReader()
    writer = _TextGatewayWriter()
    task = asyncio.create_task(gateway.handle_connection(reader, writer))
    while not writer.frames:
        await asyncio.sleep(0)
    challenge = json.loads(writer.frames[0])
    reader.feed_data(encode_frame({"type": "auth", "version": gateway.app.config["DEVICE_PROTOCOL_VERSION"], "device_id": device_id, "hmac": calculate_hmac(secret, device_id, challenge["nonce"])}))
    while len(writer.frames) < 3:
        await asyncio.sleep(0)
    reader.feed_data(b"PONG\n")
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


def test_v2_protocol_parses_ascii_frames_and_decodes_inputs_without_phases():
    assert encode_v2_frame("SETALL 1") == b"SETALL 1\n"
    assert decode_v2_frame(b"OK ALL 1\n", 128) == ("OK", ["ALL", "1"])
    actual, telemetry = parse_v2_state("O=5 U2=EF U3=A6 CSQ=20 CREG=1 CGATT=1 TEMP=42".split())
    assert actual == {
        "outputs": {"C6": 1, "C7": 0, "C8": 1},
        "inputs": {"SW2": 1, "SW3": 1, "SW4": 1, "SW5": 1, "REF": 1, "AUX0": 0, "G1": 1, "G2": 1, "G3": 0, "G4": 0, "G5": 1, "AUX6": 0},
        "raw": {"U2": "EF", "U3": "A6"},
    }
    assert telemetry == {"csq": 20, "creg": 1, "cgatt": 1, "temp": 42}


def test_v2_protocol_rejects_invalid_output_and_hex_masks():
    for args in (["O=8"], ["O=-1"], ["U2=GG"], ["U3=1FF"]):
        try:
            parse_v2_state(args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid v2 state was accepted: {args}")


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


def test_v2_keeps_json_auth_then_switches_to_ascii_authenticated_get_and_pong(app):
    secret = _gateway_device(app)
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        device.protocol_version = "2"
        db.session.commit()
    frames = asyncio.run(_authenticate_v2(Gateway(app), "board-01", secret))
    assert json.loads(frames[0])["type"] == "challenge"
    assert frames[1:] == ["AUTHENTICATED 2", "GET"]


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


def test_gateway_dispatches_one_exact_multi_output_command(app):
    _gateway_device(app)
    gateway = Gateway(app)
    writer = _GatewayWriter()
    with app.app_context():
        app.config["DEVICE_COMMAND_POLL_SECONDS"] = 0.01
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        command = DeviceCommand(
            device_id=device.id,
            command_type="switch",
            payload={"C6": 1, "C7": 1, "C8": 1},
        )
        db.session.add(command)
        db.session.commit()
        command_id = command.command_id
    gateway.connections["board-01"] = writer

    async def dispatch_once():
        task = asyncio.create_task(gateway.dispatch_commands())
        while not writer.frames:
            await asyncio.sleep(0.005)
        gateway.stopping.set()
        await task

    asyncio.run(dispatch_once())
    assert writer.frames == [
        {
            "type": "command",
            "command_id": command_id,
            "command": "switch",
            "payload": {"C6": 1, "C7": 1, "C8": 1},
        }
    ]
    with app.app_context():
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.command_id == command_id))
        assert command.status == "sent"


def test_gateway_accepts_new_state_shape_without_phases_and_preserves_raw_values(app):
    _gateway_device(app)
    gateway = Gateway(app)
    gateway._set_connection(
        "board-01",
        "online",
        actual={
            "outputs": {"C6": 1, "C7": 0, "C8": 1},
            "inputs": {"SW2": 0, "REF": 1},
            "raw": {"G1": 1, "opaque": {"value": 42}},
        },
        telemetry={"csq": 20, "uptime_s": 12345, "custom": "ok"},
    )
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        assert device.actual_state == {
            "outputs": {"C6": 1, "C7": 0, "C8": 1},
            "inputs": {"SW2": 0, "REF": 1},
            "raw": {"G1": 1, "opaque": {"value": 42}},
        }
        assert device.telemetry == {"csq": 20, "uptime_s": 12345, "custom": "ok"}
        assert device.last_state_at is not None


def test_v2_gateway_state_and_ok_complete_command_without_changing_actual(app):
    _gateway_device(app)
    gateway = Gateway(app)
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        device.protocol_version = "2"
        device.actual_state = {"outputs": {"C6": 0, "C7": 0, "C8": 0}}
        command = DeviceCommand(device_id=device.id, command_type="switch", payload={"C6": 1}, status="sent")
        db.session.add(command)
        db.session.commit()
        command_id = command.command_id

    gateway._handle_v2_frame("board-01", "127.0.0.1", "OK", ["6", "1"])
    with app.app_context():
        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.command_id == command_id))
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        assert command.status == "completed"
        assert command.acknowledged_at is not None
        assert device.actual_state["outputs"]["C6"] == 0

    gateway._handle_v2_frame("board-01", "127.0.0.1", "STATE", "O=4 U2=00 U3=00 CSQ=20".split())
    with app.app_context():
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        assert device.actual_state["outputs"] == {"C6": 1, "C7": 0, "C8": 0}
        assert device.telemetry == {"csq": 20}


def test_v2_gateway_dispatches_setall_as_one_ascii_command(app):
    _gateway_device(app)
    gateway = Gateway(app)
    writer = _TextGatewayWriter()
    with app.app_context():
        app.config["DEVICE_COMMAND_POLL_SECONDS"] = 0.01
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        device.protocol_version = "2"
        command = DeviceCommand(device_id=device.id, command_type="switch", payload={"C6": 0, "C7": 0, "C8": 0})
        db.session.add(command)
        db.session.commit()
    gateway.connections["board-01"] = writer

    async def dispatch_once():
        task = asyncio.create_task(gateway.dispatch_commands())
        while not writer.frames:
            await asyncio.sleep(0.005)
        gateway.stopping.set()
        await task

    asyncio.run(dispatch_once())
    assert writer.frames == ["SETALL 0"]


def test_diagnostic_state_samples_are_opt_in(app):
    _gateway_device(app)
    gateway = Gateway(app)
    gateway._handle_v2_frame("board-01", None, "STATE", "O=5 U2=EF U3=FB CSQ=27 CREG=1 CGATT=1".split())
    with app.app_context():
        assert db.session.scalar(db.select(DeviceDiagnosticSample)) is None
        device = db.session.scalar(db.select(Device).where(Device.device_id == "board-01"))
        device.diagnostic_mode = True
        db.session.commit()
    gateway._handle_v2_frame("board-01", None, "STATE", "O=5 U2=EF U3=FB CSQ=27 CREG=1 CGATT=1".split())
    with app.app_context():
        sample = db.session.scalar(db.select(DeviceDiagnosticSample))
        assert (sample.outputs_mask, sample.raw_u2, sample.raw_u3, sample.csq) == (5, "EF", "FB", "27")
