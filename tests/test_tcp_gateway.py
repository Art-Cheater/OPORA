from app.extensions import db
from app.models.devices import Device, DeviceCommand
from app.tcp_gateway.protocol import calculate_hmac, decode_frame, encode_frame, hmac_matches, new_nonce


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
