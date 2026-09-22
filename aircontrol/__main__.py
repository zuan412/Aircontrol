"""Main application launcher for Aircontrol."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from typing import Any, Optional

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("aircontrol")


class EngineRunner:
    """Runs the asyncio backend (ConnectionManager + ScreenStreamServer) in a dedicated daemon thread."""

    def __init__(self, port: int = 8080, udid: Optional[str] = None, via_wifi: bool = False) -> None:
        self.port = port
        self.udid = udid
        self.via_wifi = via_wifi
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None

        self.conn_mgr: Optional[Any] = None
        self.stream_server: Optional[Any] = None
        self.device_info: Optional[Any] = None
        self.actual_url: str = f"http://127.0.0.1:{port}"
        self._ready_event = threading.Event()
        self._server_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="AircontrolEngineThread")
        self.thread.start()
        self._ready_event.wait(timeout=6.0)

    def _run_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._async_main())

    async def _async_main(self) -> None:
        from aircontrol.core.connection import ConnectionManager
        from aircontrol.core.stream_server import StreamServer
        from pymobiledevice3.remote.core_device.screen_stream import ScreenStreamServer

        self.conn_mgr = ConnectionManager()

        # Connect to iPhone
        try:
            print(f"[Aircontrol] Đang tìm kiếm thiết bị iPhone ({'Wi-Fi' if self.via_wifi else 'USB'})...")
            devices = await self.conn_mgr.list_devices()
            target_udid = self.udid or (devices[0].udid if devices else None)

            if target_udid:
                print(f"[Aircontrol] Đang kết nối tới iPhone (UDID: {target_udid})...")
                self.device_info = await self.conn_mgr.connect(udid=target_udid, via_wifi=self.via_wifi)
                dev_name = self.device_info.name or "iPhone"
                dev_model = self.device_info.product_type or "iOS"
                print(f"[Aircontrol] Đã kết nối thành công tới: {dev_name} ({dev_model})")

                # Use battle-tested ScreenStreamServer with hardware WebCodecs
                self.stream_server = ScreenStreamServer(
                    rsd=self.conn_mgr.rsd,
                    bind="127.0.0.1",
                    http_port=self.port,
                    audio_default_on=False,
                )
                self.actual_url = f"http://127.0.0.1:{self.port}"
                self._ready_event.set()
                await self.stream_server.serve()
            else:
                print("[Aircontrol] Chưa phát hiện iPhone. Khởi động màn hình chờ...")
                # Start fallback standby server
                fallback = StreamServer(host="127.0.0.1", port=self.port)
                await fallback.start()
                self.stream_server = fallback
                self.actual_url = fallback.url
                self._ready_event.set()

                # Poll for connection
                while True:
                    await asyncio.sleep(2.0)
                    devs = await self.conn_mgr.list_devices()
                    if devs:
                        print(f"[Aircontrol] Phát hiện thiết bị mới cắm vào: {devs[0].udid}. Đang khởi động lại luồng...")
                        await fallback.stop()
                        self.device_info = await self.conn_mgr.connect(udid=devs[0].udid, via_wifi=self.via_wifi)
                        self.stream_server = ScreenStreamServer(
                            rsd=self.conn_mgr.rsd,
                            bind="127.0.0.1",
                            http_port=self.port,
                            audio_default_on=False,
                        )
                        await self.stream_server.serve()
                        break
        except Exception as e:
            print(f"[Aircontrol] Lỗi kết nối thiết bị: {e}")
            self._ready_event.set()

    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            async def _cleanup():
                if self.conn_mgr:
                    try:
                        await self.conn_mgr.disconnect()
                    except Exception:
                        pass
            asyncio.run_coroutine_threadsafe(_cleanup(), self.loop)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aircontrol - Bespoke iPhone Mirror & Remote Control")
    parser.add_argument("--udid", type=str, default=None, help="Target iPhone UDID")
    parser.add_argument("--wifi", action="store_true", help="Connect via Wi-Fi Bonjour instead of USB")
    parser.add_argument("--port", type=int, default=8080, help="Local HTTP stream port (default: 8080)")
    parser.add_argument("--no-gui", action="store_true", help="Run in headless server-only mode")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    runner = EngineRunner(port=args.port, udid=args.udid, via_wifi=args.wifi)
    runner.start()

    actual_url = runner.actual_url
    device_name = (
        runner.device_info.name
        if runner.device_info and runner.device_info.name
        else "iPhone"
    )

    print(f"[Aircontrol] Giao diện WebCodecs sẵn sàng tại: {actual_url}")

    if args.no_gui:
        print("[Aircontrol] Đang chạy ở chế độ Headless (nhấn Ctrl+C để thoát)...")
        try:
            while True:
                import time
                time.sleep(1.0)
        except KeyboardInterrupt:
            runner.stop()
            return 0

    from aircontrol.ui.app import AircontrolApp

    app = AircontrolApp(sys.argv)
    window = app.create_window(
        stream_url=actual_url,
        device_name=device_name,
        hid_bridge=getattr(runner.stream_server, "hid_bridge", None),
    )
    window.show()

    ret = app.run()
    runner.stop()
    return ret


if __name__ == "__main__":
    sys.exit(main())
