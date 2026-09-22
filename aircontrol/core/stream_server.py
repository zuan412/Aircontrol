"""StreamServer: A lightweight, asynchronous HTTP server distributing HEVC feeds and input events."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

from aiohttp import web

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class StreamServer:
    """HTTP and Stream server for WebCodecs client and control API."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        rsd: Any = None,
        on_touch: Optional[Callable[[str, float, float], Any]] = None,
        on_button: Optional[Callable[[str], Any]] = None,
        on_key: Optional[Callable[[str, str], Any]] = None,
    ) -> None:
        self.host = host
        self.requested_port = port
        self.rsd = rsd
        self.on_touch = on_touch
        self.on_button = on_button
        self.on_key = on_key

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._bound_port: int = 0
        self._is_streaming: bool = False
        self._stream_subscribers: Set[web.StreamResponse] = set()
        self._pmd_stream_task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._site is not None

    @property
    def port(self) -> int:
        return self._bound_port

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self._bound_port}"

    async def start(self) -> None:
        """Start the HTTP server on the configured host/port."""
        if self.is_running:
            return

        self._app = web.Application()
        self._setup_routes()

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.requested_port)
        await self._site.start()

        # Retrieve actual bound port (important when port=0)
        assert self._site._server is not None
        sockets = self._site._server.sockets
        if sockets:
            self._bound_port = sockets[0].getsockname()[1]
        else:
            self._bound_port = self.requested_port

        logger.info("Aircontrol StreamServer started on %s", self.url)

    async def stop(self) -> None:
        """Stop server and disconnect active clients."""
        if self._pmd_stream_task and not self._pmd_stream_task.done():
            self._pmd_stream_task.cancel()
            try:
                await self._pmd_stream_task
            except asyncio.CancelledError:
                pass
            self._pmd_stream_task = None

        for sub in list(self._stream_subscribers):
            try:
                await sub.write_eof()
            except Exception:
                pass
        self._stream_subscribers.clear()

        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

        self._bound_port = 0
        logger.info("Aircontrol StreamServer stopped")

    def broadcast_frame(self, data: bytes) -> None:
        """Broadcast a framed HEVC access unit (4-byte length prefix + data) to all web clients."""
        if not self._stream_subscribers:
            return
        payload = len(data).to_bytes(4, byteorder="big") + data
        for resp in list(self._stream_subscribers):
            try:
                resp.write(payload)
            except Exception:
                self._stream_subscribers.discard(resp)

    def _setup_routes(self) -> None:
        assert self._app is not None
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/status", self._handle_status)
        self._app.router.add_get("/stream", self._handle_stream)
        self._app.router.add_post("/touch", self._handle_touch)
        self._app.router.add_post("/button", self._handle_button)
        self._app.router.add_post("/key", self._handle_key)

        # Static files
        if WEB_DIR.exists():
            self._app.router.add_static("/static", str(WEB_DIR))
            if (WEB_DIR / "app.js").exists():
                self._app.router.add_get("/app.js", lambda r: web.FileResponse(str(WEB_DIR / "app.js")))
            if (WEB_DIR / "style.css").exists():
                self._app.router.add_get("/style.css", lambda r: web.FileResponse(str(WEB_DIR / "style.css")))

    async def _handle_index(self, request: web.Request) -> web.Response:
        index_file = WEB_DIR / "index.html"
        if index_file.exists():
            return web.FileResponse(str(index_file))
        return web.Response(
            text="""<!DOCTYPE html>
<html>
<head><title>Aircontrol Stream</title></head>
<body><h2>Aircontrol Engine Running</h2><p>Connect client or embed in Aircontrol Desktop App.</p></body>
</html>""",
            content_type="text/html",
        )

    async def _handle_status(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "streaming": self._is_streaming,
            "subscribers": len(self._stream_subscribers),
            "device": getattr(self.rsd, "name", "None") if self.rsd else "None",
        })

    async def _handle_stream(self, request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "application/octet-stream",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        self._stream_subscribers.add(response)
        try:
            while not response.prepared or not request.transport.is_closing():
                await asyncio.sleep(1.0)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self._stream_subscribers.discard(response)
        return response

    async def _handle_touch(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            action = data.get("action", "move")
            x = float(data.get("x", 0.0))
            y = float(data.get("y", 0.0))
            if self.on_touch:
                res = self.on_touch(action, x, y)
                if asyncio.iscoroutine(res):
                    await res
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _handle_button(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            button = data.get("button", "")
            if self.on_button and button:
                res = self.on_button(button)
                if asyncio.iscoroutine(res):
                    await res
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def _handle_key(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            key = data.get("key", "")
            code = data.get("code", "")
            if self.on_key:
                res = self.on_key(key, code)
                if asyncio.iscoroutine(res):
                    await res
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
