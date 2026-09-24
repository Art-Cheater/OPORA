"""Asyncio TCP gateway process. It intentionally does not run in Gunicorn."""

from __future__ import annotations

import argparse
import asyncio
import signal
from contextlib import suppress
from datetime import timedelta
from typing import Any

from flask import Flask

from app import create_app
from app.extensions import db
from app.models.base import as_utc_aware, utcnow
from app.models.devices import Device, DeviceCommand, DeviceDiagnosticSample
from app.models.devices.state import apply_input_test_sample, normalize_actual_state, observe_raw_bits, payload_matches_actual
from app.modules.devices.command_service import expire_state_confirmation_timeouts
from app.tcp_gateway.protocol import decode_frame, decode_v2_frame, encode_frame, encode_v2_frame, hmac_matches, new_nonce, parse_v2_state
from app.tcp_gateway.secrets import decrypt_device_secret


class Gateway:
    def __init__(self, app: Flask):
        self.app = app
        self.connections: dict[str, asyncio.StreamWriter] = {}
        self.connection_protocols: dict[str, str] = {}
        self.last_diagnostic_get: dict[str, float] = {}
        self.stopping = asyncio.Event()

    def _get_authenticated_device_secret(self, device_id: str) -> str | None:
        """Return an enabled device's decrypted secret inside Flask context."""
        with self.app.app_context():
            device = db.session.scalar(
                db.select(Device).where(
                    Device.device_id == device_id,
                    Device.active_filter(),
                )
            )
            if device is None or not device.enabled:
                return None
            return decrypt_device_secret(device.secret_encrypted)

    def _set_connection(
        self,
        device_id: str,
        state: str,
        peer: str | None = None,
        actual: dict[str, Any] | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        with self.app.app_context():
            device = db.session.scalar(db.select(Device).where(Device.device_id == device_id, Device.active_filter()))
            if device:
                now = utcnow()
                device.connection_state = state
                device.last_seen_at = now
                if peer:
                    device.last_ip = peer
                if actual is not None:
                    actual = observe_raw_bits(device.actual_state, actual, now.isoformat())
                    if device.input_test_session:
                        device.input_test_session = apply_input_test_sample(device.input_test_session, actual.get("raw"), now.isoformat())
                    device.actual_state = normalize_actual_state(actual)
                    awaiting_confirmation = db.session.scalars(
                        db.select(DeviceCommand).where(
                            DeviceCommand.device_id == device.id,
                            DeviceCommand.status == "acknowledged",
                            DeviceCommand.state_confirmed_at.is_(None),
                            DeviceCommand.active_filter(),
                        )
                    ).all()
                    for command in awaiting_confirmation:
                        if payload_matches_actual(command.payload, device.actual_state):
                            command.state_confirmed_at = now
                        else:
                            command.status = "failed"
                            command.failed_at = now
                            command.error = "State does not match requested outputs"
                if actual is not None or telemetry is not None:
                    device.last_state_at = now
                if isinstance(telemetry, dict):
                    device.telemetry = telemetry
                if device.diagnostic_mode and actual is not None:
                    outputs, raw = (device.actual_state or {}).get("outputs", {}), (device.actual_state or {}).get("raw", {})
                    db.session.add(DeviceDiagnosticSample(device_id=device.id, outputs_mask=(int(outputs.get("C6", 0)) << 2) | (int(outputs.get("C7", 0)) << 1) | int(outputs.get("C8", 0)), raw_u2=raw.get("U2"), raw_u3=raw.get("U3"), csq=str((telemetry or {}).get("csq")) if (telemetry or {}).get("csq") is not None else None, creg=str((telemetry or {}).get("creg")) if (telemetry or {}).get("creg") is not None else None, cgatt=str((telemetry or {}).get("cgatt")) if (telemetry or {}).get("cgatt") is not None else None))
                db.session.commit()

    async def _send(self, writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        writer.write(encode_frame(payload))
        await writer.drain()

    async def _send_v2(self, writer: asyncio.StreamWriter, command: str) -> None:
        writer.write(encode_v2_frame(command))
        await writer.drain()

    def _protocol_for_device(self, device_id: str) -> str:
        with self.app.app_context():
            device = db.session.scalar(db.select(Device).where(Device.device_id == device_id, Device.active_filter()))
            return "2" if device is not None and device.protocol_version == "2" else "1"

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if isinstance(peer, tuple) else None
        device_id: str | None = None
        try:
            nonce = new_nonce()
            await self._send(writer, {"type": "challenge", "version": self.app.config["DEVICE_PROTOCOL_VERSION"], "nonce": nonce})
            raw = await asyncio.wait_for(reader.readline(), timeout=self.app.config["DEVICE_AUTH_TIMEOUT_SECONDS"])
            auth = decode_frame(raw, self.app.config["DEVICE_MAX_FRAME_BYTES"])
            if auth.get("type") != "auth" or auth.get("version") != self.app.config["DEVICE_PROTOCOL_VERSION"]:
                return
            device_id = str(auth.get("device_id") or "")
            secret = self._get_authenticated_device_secret(device_id)
            if secret is None:
                return
            if not hmac_matches(secret, device_id, nonce, str(auth.get("hmac") or "")):
                return
            old = self.connections.get(device_id)
            if old and old is not writer:
                old.close()
            self.connections[device_id] = writer
            protocol_version = self._protocol_for_device(device_id)
            self.connection_protocols[device_id] = protocol_version
            self._set_connection(device_id, "online", peer_ip)
            if protocol_version == "2":
                await self._send_v2(writer, "AUTHENTICATED 2")
                await self._send_v2(writer, "GET")
            else:
                await self._send(writer, {"type": "authenticated", "version": self.app.config["DEVICE_PROTOCOL_VERSION"]})
            while not self.stopping.is_set():
                try:
                    raw = await asyncio.wait_for(reader.readline(), timeout=self.app.config["DEVICE_PING_SECONDS"])
                except asyncio.TimeoutError:
                    if protocol_version == "2":
                        await self._send_v2(writer, "PING")
                    else:
                        await self._send(writer, {"type": "ping"})
                    raw = await asyncio.wait_for(reader.readline(), timeout=self.app.config["DEVICE_PONG_TIMEOUT_SECONDS"])
                if protocol_version == "2":
                    verb, args = decode_v2_frame(raw, self.app.config["DEVICE_MAX_FRAME_BYTES"])
                    self._handle_v2_frame(device_id, peer_ip, verb, args)
                else:
                    frame = decode_frame(raw, self.app.config["DEVICE_MAX_FRAME_BYTES"])
                    kind = frame.get("type")
                    if kind == "pong":
                        self._set_connection(device_id, "online", peer_ip)
                    elif kind == "state":
                        state = frame.get("actual")
                        telemetry = frame.get("telemetry")
                        self._set_connection(device_id, "online", peer_ip, state if isinstance(state, dict) else None, telemetry if isinstance(telemetry, dict) else None)
                    elif kind == "ack":
                        self._ack(device_id, str(frame.get("command_id") or ""), bool(frame.get("ok", True)), str(frame.get("error") or ""), protocol_version="1")
        except (ConnectionError, asyncio.IncompleteReadError, ValueError, TimeoutError):
            pass
        except Exception:
            self.app.logger.exception("TCP gateway connection failed")
        finally:
            if device_id and self.connections.get(device_id) is writer:
                self.connections.pop(device_id, None)
                self.connection_protocols.pop(device_id, None)
                self._set_connection(device_id, "offline")
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    def _handle_v2_frame(self, device_id: str, peer_ip: str | None, verb: str, args: list[str]) -> None:
        if verb == "PONG":
            self._set_connection(device_id, "online", peer_ip)
        elif verb == "STATE":
            actual, telemetry = parse_v2_state(args)
            self._set_connection(device_id, "online", peer_ip, actual, telemetry)
        elif verb == "OK":
            self._ack_latest(device_id, True, "")
        elif verb == "ERR":
            self._ack_latest(device_id, False, " ".join(args)[:500] or "Device error")
        else:
            raise ValueError("unknown v2 frame")

    def _ack_latest(self, device_id: str, success: bool, error: str) -> None:
        with self.app.app_context():
            command = db.session.scalar(
                db.select(DeviceCommand).join(Device).where(
                    Device.device_id == device_id,
                    DeviceCommand.status == "sent",
                    DeviceCommand.active_filter(),
                ).order_by(DeviceCommand.sent_at.desc())
            )
            command_id = command.command_id if command else ""
        self._ack(device_id, command_id, success, error, protocol_version="2")

    def _ack(self, device_id: str, command_id: str, success: bool, error: str, *, protocol_version: str = "1") -> None:
        with self.app.app_context():
            command = db.session.scalar(db.select(DeviceCommand).join(Device).where(Device.device_id == device_id, DeviceCommand.command_id == command_id))
            if command and command.status == "sent":
                command.status = "completed" if success and protocol_version == "2" else ("acknowledged" if success else "failed")
                command.acknowledged_at = utcnow() if success else None
                command.failed_at = utcnow() if not success else None
                command.error = error or None
                device = db.session.get(Device, command.device_id)
                state_is_newer = (
                    device is not None
                    and device.last_state_at is not None
                    and as_utc_aware(device.last_state_at) >= as_utc_aware(command.created_at)
                )
                if success and protocol_version == "1" and state_is_newer and payload_matches_actual(command.payload, device.actual_state):
                    command.state_confirmed_at = utcnow()
                db.session.commit()

    async def dispatch_commands(self) -> None:
        while not self.stopping.is_set():
            with self.app.app_context():
                stale_before = utcnow() - timedelta(seconds=self.app.config["DEVICE_COMMAND_TIMEOUT_SECONDS"])
                stale = db.session.scalars(db.select(DeviceCommand).where(DeviceCommand.status == "sent", DeviceCommand.sent_at < stale_before)).all()
                for command in stale:
                    command.status, command.failed_at, command.error = "timeout", utcnow(), "ACK timeout"
                expire_state_confirmation_timeouts()
                pending = db.session.scalars(db.select(DeviceCommand).join(Device).where(DeviceCommand.status == "pending", Device.active_filter())).all()
                db.session.commit()
                outbound = [(item.device_id, item.command_id, item.command_type, item.payload) for item in pending]
                diagnostic = [(item.id, item.device_id) for item in db.session.scalars(db.select(Device).where(Device.diagnostic_mode.is_(True), Device.protocol_version == "2", Device.connection_state == "online", Device.active_filter())).all()]
            for device_pk, command_id, command_type, payload in outbound:
                with self.app.app_context():
                    device = db.session.get(Device, device_pk)
                    writer = self.connections.get(device.device_id) if device else None
                    protocol_version = device.protocol_version if device else "1"
                if not writer or writer.is_closing():
                    continue
                try:
                    if protocol_version == "2":
                        await self._send_v2(writer, self._v2_command(command_type, payload or {}))
                    else:
                        await self._send(writer, {"type": "command", "command_id": command_id, "command": command_type, "payload": payload or {}})
                    with self.app.app_context():
                        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.command_id == command_id))
                        if command and command.status == "pending":
                            command.status, command.sent_at = "sent", utcnow()
                            db.session.commit()
                except ConnectionError:
                    continue
            now_loop = asyncio.get_running_loop().time()
            busy_ids = {device_pk for device_pk, *_ in outbound}
            for device_pk, external_id in diagnostic:
                if device_pk in busy_ids or now_loop - self.last_diagnostic_get.get(external_id, 0) < 1:
                    continue
                writer = self.connections.get(external_id)
                if writer and not writer.is_closing():
                    try:
                        await self._send_v2(writer, "GET")
                        self.last_diagnostic_get[external_id] = now_loop
                    except ConnectionError:
                        continue
            await asyncio.sleep(self.app.config["DEVICE_COMMAND_POLL_SECONDS"])

    @staticmethod
    def _v2_command(command_type: str, payload: dict[str, Any]) -> str:
        """Translate only validated OPORA switch commands into v2 wire text."""
        if command_type != "switch":
            raise ValueError("unsupported v2 command")
        values = {key: int(value) for key, value in payload.items()}
        if set(values) == {"C6", "C7", "C8"} and len(set(values.values())) == 1 and next(iter(values.values())) in {0, 1}:
            return f"SETALL {next(iter(values.values()))}"
        if len(values) == 1:
            relay, value = next(iter(values.items()))
            if relay in {"C6", "C7", "C8"} and value in {0, 1}:
                return f"SET {relay[1:]} {value}"
        raise ValueError("invalid v2 switch payload")

    async def health(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"ok\n")
        await writer.drain()
        writer.close()

    async def run(self) -> None:
        tcp = await asyncio.start_server(self.handle_connection, self.app.config["DEVICE_GATEWAY_HOST"], self.app.config["DEVICE_GATEWAY_PORT"], limit=self.app.config["DEVICE_MAX_FRAME_BYTES"] + 1)
        health = await asyncio.start_server(self.health, "127.0.0.1", self.app.config["DEVICE_HEALTH_PORT"])
        dispatcher = asyncio.create_task(self.dispatch_commands())
        async with tcp, health:
            await self.stopping.wait()
        dispatcher.cancel()
        with suppress(asyncio.CancelledError):
            await dispatcher


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    app = create_app()
    if args.healthcheck:
        async def check() -> None:
            reader, writer = await asyncio.open_connection("127.0.0.1", app.config["DEVICE_HEALTH_PORT"])
            assert (await reader.readline()).strip() == b"ok"
            writer.close()
        asyncio.run(check())
        return
    gateway = Gateway(app)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, gateway.stopping.set)
    loop.run_until_complete(gateway.run())


if __name__ == "__main__":
    main()
