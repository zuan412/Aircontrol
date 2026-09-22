import pytest
import aiohttp
from aircontrol.core.stream_server import StreamServer


@pytest.mark.asyncio
async def test_stream_server_lifecycle():
    server = StreamServer(host="127.0.0.1", port=0)
    assert not server.is_running

    await server.start()
    assert server.is_running
    assert server.port > 0

    # Verify HTTP status endpoint
    url = f"http://127.0.0.1:{server.port}/status"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            assert resp.status == 200
            data = await resp.json()
            assert "status" in data
            assert data["status"] == "ok"

    await server.stop()
    assert not server.is_running
