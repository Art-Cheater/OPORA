"""Minimal raw TCP sniffer; TCP chunks are logged exactly as received."""
from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime, timezone

LOG = logging.getLogger("opora.modem_sniffer")


def format_chunk(data: bytes, ip: str) -> str:
    text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data)
    return f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} IP={ip} LEN:{len(data)} HEX:{data.hex(' ').upper()} ASCII:{text}"


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername") or ("?", "?")
    ip, port = str(peer[0]), str(peer[1])
    LOG.info("MODEM CONNECT IP=%s PORT=%s", ip, port)
    try:
        while data := await reader.read(4096):
            LOG.info("%s", format_chunk(data, ip))
    finally:
        LOG.info("MODEM DISCONNECT IP=%s PORT=%s", ip, port)
        writer.close()
        await writer.wait_closed()


async def run(host: str | None = None, port: int | None = None) -> None:
    server = await asyncio.start_server(handle, host or os.getenv("MODEM_GATEWAY_HOST", "0.0.0.0"), port or int(os.getenv("MODEM_SNIFFER_PORT", "5009")))
    async with server:
        await server.serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
