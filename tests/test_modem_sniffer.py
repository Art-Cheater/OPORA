import asyncio
from app.modem_gateway.sniffer import format_chunk, handle

def test_raw_tcp_sniffer_receives_bytes(caplog):
    async def scenario():
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(bytes([1, 2, 3, 4])); await writer.drain(); writer.close(); await writer.wait_closed()
        await asyncio.sleep(0.05); server.close(); await server.wait_closed()
    asyncio.run(scenario())
    assert "01 02 03 04" in format_chunk(bytes([1, 2, 3, 4]), "127.0.0.1")
