"""Aircontrol Stream Server: High-performance Apple CoreDevice screen streaming and input bridging."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from pathlib import Path
from typing import Any, Optional

from pymobiledevice3.remote.core_device import screen_stream
from pymobiledevice3.remote.core_device.screen_stream import ScreenStreamServer

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def find_available_port(start_port: int = 8080, max_range: int = 50) -> int:
    """Find a guaranteed available TCP port on localhost to avoid Errno 10048."""
    if start_port == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    for port in range(start_port, start_port + max_range):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


def configure_bespoke_viewer() -> None:
    """Inject our custom iPhone 16 Pro mockup and WebCodecs engine into pymobiledevice3's viewer."""
    html_path = WEB_DIR / "index.html"
    css_path = WEB_DIR / "style.css"
    js_path = WEB_DIR / "app.js"

    if html_path.exists():
        screen_stream.VIEWER_HTML = html_path.read_bytes()
    if css_path.exists():
        screen_stream.VIEWER_CSS = css_path.read_bytes()
    if js_path.exists():
        screen_stream.VIEWER_JS_TEMPLATE = js_path.read_bytes()


class AircontrolStreamServer(ScreenStreamServer):
    """Bespoke ScreenStreamServer that serves our custom iPhone 16 Pro UI,
    bypasses macOS-only audio dependencies on Windows, and integrates directly with PySide6."""

    def __init__(self, rsd: Any, bind: str = "127.0.0.1", http_port: int = 8080) -> None:
        configure_bespoke_viewer()
        self.actual_port = find_available_port(http_port)
        super().__init__(
            rsd=rsd,
            bind=bind,
            http_port=self.actual_port,
            audio_default_on=False,
        )

    async def _ensure_audio_stream(self) -> None:
        """AudioToolbox AAC-ELD decode is macOS-only; safely bypass on Windows."""
        return

    @property
    def url(self) -> str:
        return f"http://{self._bind}:{self.actual_port}"


class AircontrolFallbackServer:
    """Lightweight HTTP server serving the standby iPhone UI and diagnostics while waiting for device connection."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080, rsd: Any = None) -> None:
        self.host = host
        self.requested_port = port
        self.rsd = rsd
        self._port = find_available_port(port)
        self._server: Optional[asyncio.Server] = None
        self._live_stream_server: Optional[AircontrolStreamServer] = None
        self.hid_bridge: Optional[Any] = None

    @property
    def is_running(self) -> bool:
        return self._server is not None or self._live_stream_server is not None

    @property
    def port(self) -> int:
        if self._live_stream_server is not None:
            return self._live_stream_server.actual_port
        return self._port

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle_http, self.host, self._port)
        # Update actual port if port=0 was requested
        if self._server.sockets:
            self._port = self._server.sockets[0].getsockname()[1]
        logger.info("Aircontrol Server running on %s", self.url)

    async def stop(self) -> None:
        if self._live_stream_server is not None:
            try:
                await self._live_stream_server._stop_active_stream()
            except Exception:
                pass
            self._live_stream_server = None

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Aircontrol Server stopped")

    async def attach_device(self, rsd: Any) -> None:
        """Attach connected iOS device and prepare streaming bridge."""
        self.rsd = rsd
        from aircontrol.core.hid_bridge import HIDBridge
        self.hid_bridge = HIDBridge(rsd=rsd)

    async def start_device_streaming(self) -> None:
        """Start full ScreenStreamServer on the device."""
        if not self.rsd:
            logger.warning("Cannot start device streaming: No RSD connected")
            return
        if self._server:
            await self.stop()
        self._live_stream_server = AircontrolStreamServer(
            rsd=self.rsd,
            bind=self.host,
            http_port=self._port,
        )
        asyncio.create_task(self._live_stream_server.serve())

    async def _handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                return
            while True:
                h = await reader.readline()
                if h in (b"\r\n", b"", b"\n"):
                    break
            parts = line.split()
            path = parts[1].decode().split("?")[0] if len(parts) >= 2 else "/"

            if path in ("/", "/index.html"):
                body = (WEB_DIR / "index.html").read_bytes()
                ctype = b"text/html; charset=utf-8"
            elif path in ("/viewer.css", "/style.css"):
                body = (WEB_DIR / "style.css").read_bytes()
                ctype = b"text/css; charset=utf-8"
            elif path in ("/viewer.js", "/app.js"):
                body = (WEB_DIR / "app.js").read_bytes()
                ctype = b"application/javascript; charset=utf-8"
            elif path == "/status":
                body = json.dumps({"status": "ok", "mode": "standby"}).encode("utf-8")
                ctype = b"application/json"
            else:
                body = b"waiting for device connection"
                ctype = b"text/plain"

            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: " + ctype + b"\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                b"Connection: close\r\n\r\n" + body
            )
            writer.write(resp)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()


def StreamServer(
    host: str = "127.0.0.1",
    port: int = 8080,
    rsd: Any = None,
    **kwargs: Any,
) -> Any:
    """Factory creating either AircontrolStreamServer (if RSD provided) or AircontrolFallbackServer."""
    if rsd is not None:
        return AircontrolStreamServer(rsd=rsd, bind=host, http_port=port)
    return AircontrolFallbackServer(host=host, port=port, rsd=rsd)
