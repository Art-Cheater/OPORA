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
from app.models.base import utcnow
from app.models.devices import Device, DeviceCommand
from app.tcp_gateway.protocol import decode_frame, encode_frame, hmac_matches, new_nonce
from app.tcp_gateway.secrets import decrypt_device_secret


class Gateway:
    def __init__(self, app: Flask):
        self.app = app
        self.connections: dict[str, asyncio.StreamWriter] = {}
        self.stopping = asyncio.Event()

    def _get_device(self, device_id: str) -> Device | None:
        with self.app.app_context():
            return db.session.scalar(db.select(Device).where(Device.device_id == device_id, Device.active_filter()))

    def _set_connection(self, device_id: str, state: str, peer: str | None = None, actual: dict[str, Any] | None = None) -> None:
        with self.app.app_context():
            device = db.session.scalar(db.select(Device).where(Device.device_id == device_id, Device.active_filter()))
            if device:
                device.connection_state = state
                device.last_seen_at = utcnow()
                if peer:
                    device.last_ip = peer
                if actual is not None:
                    device.actual_state = actual
                db.session.commit()

    async def _send(self, writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        writer.write(encode_frame(payload))
        await writer.drain()

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
            device = self._get_device(device_id)
            if not device or not device.enabled:
                return
            if not hmac_matches(decrypt_device_secret(device.secret_encrypted), device_id, nonce, str(auth.get("hmac") or "")):
                return
            old = self.connections.get(device_id)
            if old and old is not writer:
                old.close()
            self.connections[device_id] = writer
            self._set_connection(device_id, "online", peer_ip)
            await self._send(writer, {"type": "authenticated", "version": self.app.config["DEVICE_PROTOCOL_VERSION"]})
            while not self.stopping.is_set():
                try:
                    raw = await asyncio.wait_for(reader.readline(), timeout=self.app.config["DEVICE_PING_SECONDS"])
                except asyncio.TimeoutError:
                    await self._send(writer, {"type": "ping"})
                    raw = await asyncio.wait_for(reader.readline(), timeout=self.app.config["DEVICE_PONG_TIMEOUT_SECONDS"])
                frame = decode_frame(raw, self.app.config["DEVICE_MAX_FRAME_BYTES"])
                kind = frame.get("type")
                if kind == "pong":
                    self._set_connection(device_id, "online", peer_ip)
                elif kind == "state":
                    state = frame.get("actual")
                    self._set_connection(device_id, "online", peer_ip, state if isinstance(state, dict) else None)
                elif kind == "ack":
                    self._ack(device_id, str(frame.get("command_id") or ""), bool(frame.get("ok", True)), str(frame.get("error") or "")[:500])
        except (ConnectionError, asyncio.IncompleteReadError, ValueError, TimeoutError):
            pass
        except Exception:
            self.app.logger.exception("TCP gateway connection failed")
        finally:
            if device_id and self.connections.get(device_id) is writer:
                self.connections.pop(device_id, None)
                self._set_connection(device_id, "offline")
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    def _ack(self, device_id: str, command_id: str, success: bool, error: str) -> None:
        with self.app.app_context():
            command = db.session.scalar(db.select(DeviceCommand).join(Device).where(Device.device_id == device_id, DeviceCommand.command_id == command_id))
            if command and command.status == "sent":
                command.status = "acknowledged" if success else "failed"
                command.acknowledged_at = utcnow() if success else None
                command.failed_at = utcnow() if not success else None
                command.error = error or None
                db.session.commit()

    async def dispatch_commands(self) -> None:
        while not self.stopping.is_set():
            with self.app.app_context():
                stale_before = utcnow() - timedelta(seconds=self.app.config["DEVICE_COMMAND_TIMEOUT_SECONDS"])
                stale = db.session.scalars(db.select(DeviceCommand).where(DeviceCommand.status == "sent", DeviceCommand.sent_at < stale_before)).all()
                for command in stale:
                    command.status, command.failed_at, command.error = "timeout", utcnow(), "ACK timeout"
                pending = db.session.scalars(db.select(DeviceCommand).join(Device).where(DeviceCommand.status == "pending", Device.active_filter())).all()
                db.session.commit()
                outbound = [(item.device_id, item.command_id, item.command_type, item.payload) for item in pending]
            for device_pk, command_id, command_type, payload in outbound:
                with self.app.app_context():
                    device = db.session.get(Device, device_pk)
                    writer = self.connections.get(device.device_id) if device else None
                if not writer or writer.is_closing():
                    continue
                try:
                    await self._send(writer, {"type": "command", "command_id": command_id, "command": command_type, "payload": payload or {}})
                    with self.app.app_context():
                        command = db.session.scalar(db.select(DeviceCommand).where(DeviceCommand.command_id == command_id))
                        if command and command.status == "pending":
                            command.status, command.sent_at = "sent", utcnow()
                            db.session.commit()
                except ConnectionError:
                    continue
            await asyncio.sleep(self.app.config["DEVICE_COMMAND_POLL_SECONDS"])

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
