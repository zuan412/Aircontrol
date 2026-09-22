import pytest
import aiohttp
from aircontrol.core.stream_server import StreamServer


@pytest.mark.asyncio
async def test_static_web_assets_served():
    server = StreamServer(host="127.0.0.1", port=0)
    await server.start()

    async with aiohttp.ClientSession() as session:
        # Check index.html
        async with session.get(f"{server.url}/") as resp:
            assert resp.status == 200
            text = await resp.text()
            assert "iphone-chassis" in text
            assert "dynamic-island" in text

        # Check style.css
        async with session.get(f"{server.url}/style.css") as resp:
            assert resp.status == 200
            text = await resp.text()
            assert "titanium-base" in text

        # Check app.js
        async with session.get(f"{server.url}/app.js") as resp:
            assert resp.status == 200
            text = await resp.text()
            assert "VideoDecoder" in text

    await server.stop()
