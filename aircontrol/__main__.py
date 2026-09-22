"""Main application launcher for Aircontrol."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from typing import Any, Optional

logger = logging.getLogger("aircontrol")


class EngineRunner:
    """Runs the asyncio backend (ConnectionManager + StreamServer) in a dedicated daemon thread."""

    def __init__(self, port: int = 8080, udid: Optional[str] = None, via_wifi: bool = False) -> None:
        self.port = port
        self.udid = udid
        self.via_wifi = via_wifi
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None

        self.conn_mgr: Optional[Any] = None
        self.stream_server: Optional[Any] = None
        self.device_info: Optional[Any] = None
        self._ready_event = threading.Event()

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="AircontrolEngineThread")
        self.thread.start()
        self._ready_event.wait(timeout=5.0)

    def _run_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._async_main())

    async def _async_main(self) -> None:
        from aircontrol.core.connection import ConnectionManager
        from aircontrol.core.stream_server import StreamServer

        self.conn_mgr = ConnectionManager()
        self.stream_server = StreamServer(host="127.0.0.1", port=self.port)
        await self.stream_server.start()

        self._ready_event.set()

        # Connect to iPhone
        try:
            print(f"[Aircontrol] Đang tìm kiếm thiết bị iPhone ({'Wi-Fi' if self.via_wifi else 'USB'})...")
            devices = await self.conn_mgr.list_devices()
            target_udid = self.udid or (devices[0].udid if devices else None)

            if target_udid:
                print(f"[Aircontrol] Đang kết nối tới iPhone (UDID: {target_udid})...")
                self.device_info = await self.conn_mgr.connect(udid=target_udid, via_wifi=self.via_wifi)
                print(f"[Aircontrol] Đã kết nối thành công tới: {self.device_info.name} ({self.device_info.product_type})")
                
                await self.stream_server.attach_device(self.conn_mgr.rsd)
                await self.stream_server.start_device_streaming()
            else:
                print("[Aircontrol] Chưa phát hiện iPhone. Server đang chờ thiết bị cắm vào...")
        except Exception as e:
            print(f"[Aircontrol] Ghi chú kết nối: {e}")

        # Keep server loop alive
        while self.stream_server and self.stream_server.is_running:
            await asyncio.sleep(1.0)

    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            async def _cleanup():
                if self.stream_server:
                    await self.stream_server.stop()
                if self.conn_mgr:
                    await self.conn_mgr.disconnect()
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

    actual_url = runner.stream_server.url if runner.stream_server else f"http://127.0.0.1:{args.port}"
    device_name = runner.device_info.name if runner.device_info else "iPhone"

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
