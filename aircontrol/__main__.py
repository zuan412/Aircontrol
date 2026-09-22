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

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="AircontrolEngineThread")
        self.thread.start()
        self._ready_event.wait(timeout=10.0)

    def _run_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._async_main())

    async def _async_main(self) -> None:
        from aircontrol.core.connection import ConnectionManager
        from aircontrol.core.stream_server import (
            AircontrolStreamServer,
            AircontrolFallbackServer,
            find_available_port,
        )

        self.conn_mgr = ConnectionManager()
        allocated_port = find_available_port(self.port)
        self.port = allocated_port
        self.actual_url = f"http://127.0.0.1:{allocated_port}"

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

                self.stream_server = AircontrolStreamServer(
                    rsd=self.conn_mgr.rsd,
                    bind="127.0.0.1",
                    http_port=allocated_port,
                )
                self.actual_url = self.stream_server.url
                self._ready_event.set()
                await self.stream_server.serve()
            else:
                print("[Aircontrol] Chưa phát hiện iPhone. Khởi động màn hình chờ...")
                fallback = AircontrolFallbackServer(host="127.0.0.1", port=allocated_port)
                await fallback.start()
                self.actual_url = fallback.url
                self._ready_event.set()

                while True:
                    await asyncio.sleep(2.0)
                    devs = await self.conn_mgr.list_devices()
                    if devs:
                        print(f"[Aircontrol] Phát hiện iPhone mới cắm vào: {devs[0].udid}. Đang kết nối...")
                        await fallback.stop()
                        self.device_info = await self.conn_mgr.connect(udid=devs[0].udid, via_wifi=self.via_wifi)
                        dev_name = self.device_info.name or "iPhone"
                        dev_model = self.device_info.product_type or "iOS"
                        print(f"[Aircontrol] Đã kết nối thành công tới: {dev_name} ({dev_model})")

                        self.stream_server = AircontrolStreamServer(
                            rsd=self.conn_mgr.rsd,
                            bind="127.0.0.1",
                            http_port=allocated_port,
                        )
                        await self.stream_server.serve()
                        break
        except Exception as e:
            print(f"[Aircontrol] Lỗi kết nối thiết bị: {e}")
            self._ready_event.set()

    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            async def _cleanup():
                if self.stream_server and hasattr(self.stream_server, "_stop_active_stream"):
                    try:
                        await self.stream_server._stop_active_stream()
                    except Exception:
                        pass
                if self.conn_mgr:
                    try:
                        await self.conn_mgr.disconnect()
                    except Exception:
                        pass
            asyncio.run_coroutine_threadsafe(_cleanup(), self.loop)


def find_hardware_app_browser() -> Optional[str]:
    import os
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Aircontrol - Bespoke iPhone Mirror & Remote Control")
    parser.add_argument("--udid", type=str, default=None, help="Target iPhone UDID")
    parser.add_argument("--wifi", action="store_true", help="Connect via Wi-Fi Bonjour instead of USB")
    parser.add_argument("--port", type=int, default=8080, help="Local HTTP stream port (default: 8080)")
    parser.add_argument("--no-gui", action="store_true", help="Run in headless server-only mode")
    parser.add_argument("--qt", action="store_true", help="Force QtWebEngine GUI instead of Edge/Chrome App window")
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

    browser_bin = None if args.qt else find_hardware_app_browser()
    if browser_bin:
        import subprocess
        from pathlib import Path
        profile_dir = Path(__file__).resolve().parent.parent / ".profile"
        cmd = [
            browser_bin,
            f"--app={actual_url}",
            "--window-size=620,980",
            f"--user-data-dir={profile_dir}",
            "--disable-features=Translate",
            "--no-first-run",
            "--no-default-browser-check",
            "--app-id=aircontrol-iphone",
        ]
        print(f"[Aircontrol] Khởi động cửa sổ ứng dụng tăng tốc Direct3D 11...")
        proc = subprocess.Popen(cmd)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
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
