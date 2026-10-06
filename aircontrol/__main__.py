"""Main entry point for Aircontrol.

Wires together the 3-pillar architecture:
1. ConnectionManager: automatic USB hotplug detection and device lifecycle.
2. ScreenStreamEngine & FastHevcDecoder: 60 FPS HEVC streaming with PyAV multithreaded slice decoding.
3. HIDController: non-blocking touch, gesture swipe, and hardware buttons.
4. AircontrolWindow & VideoWidget: bespoke desktop GUI with hardware OpenGL double-buffering and VSync.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon, QSurfaceFormat
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication


if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("aircontrol")


class AircontrolAppRunner:
    """Orchestrates the background asyncio engine with the Qt main GUI loop."""

    def __init__(
        self,
        window: object,
        udid: Optional[str] = None,
        force_usb: bool = False,
        force_wifi: bool = False,
        target_ip: Optional[str] = None,
    ) -> None:
        self.window = window
        self.udid = udid
        self.force_usb = force_usb
        self.force_wifi = force_wifi
        self.target_ip = target_ip.strip() if target_ip else None
        # USB-First Smart Policy: Prefer USB if cable is plugged in; fallback to Wi-Fi
        if self.target_ip and not force_usb:
            self.via_wifi = True
        else:
            self.via_wifi = not force_usb if force_wifi else False

        self.conn_mgr: Any = None
        self.stream_engine: Any = None
        self.hid_controller: Any = None
        self.pasteboard_mgr: Any = None
        self._connect_trigger_event: Optional[asyncio.Event] = None
        self._cli_target_ip = self.target_ip

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._running = False
        self._current_stream_task: Optional[asyncio.Task[None]] = None

        # Wire hardware rotation on user rotate action (Ctrl+R / Titlebar menu)
        self.window.on_rotate_request = self.handle_rotate

        # Wire manual IP connection requests from VideoWidget input bar
        if hasattr(self.window, "video_widget") and hasattr(self.window.video_widget, "connect_ip_requested"):
            self.window.video_widget.connect_ip_requested.connect(
                lambda ip: self.connect(target_ip=ip, via_wifi=True)
            )

    def connect(self, target_ip: Optional[str] = None, via_wifi: bool = True) -> None:
        """Trigger connection to target device (e.g. via direct IP or Wi-Fi Bonjour discovery)."""
        if target_ip:
            self.target_ip = target_ip
        self.via_wifi = via_wifi
        if self._connect_trigger_event is not None and self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._connect_trigger_event.set)

    def handle_rotate(self) -> None:
        """Trigger hardware orientation rotation and fast IDR refresh."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_rotate(), self.loop)

    async def _async_rotate(self) -> None:
        if self.conn_mgr and getattr(self.conn_mgr, "rsd", None):
            try:
                from pymobiledevice3.remote.core_device.orientation_service import OrientationService, ROTATE_LEFT
                async with OrientationService(self.conn_mgr.rsd) as svc:
                    await svc.rotate(ROTATE_LEFT)
            except Exception as e:
                logger.debug("Hardware orientation rotate failed: %s", e)
        if self.stream_engine:
            self.stream_engine.trigger_orientation_keyframe()

    def start(self) -> None:
        """Start the background asyncio network thread."""
        self._running = True
        self.thread = threading.Thread(
            target=self._run_event_loop,
            name="AircontrolAsyncWorker",
            daemon=True,
        )
        self.thread.start()

    def _run_event_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._connect_trigger_event = asyncio.Event()
        try:
            from aircontrol.core.connection import ConnectionManager
            self.conn_mgr = ConnectionManager()
            self.loop.run_until_complete(self._supervise_connection_loop())
        except (RuntimeError, asyncio.CancelledError):
            pass
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            try:
                self.loop.close()
            except Exception:
                pass

    async def _supervise_connection_loop(self) -> None:
        """Continuously monitor device connectivity and handle stream sessions."""
        assert self.loop is not None

        from aircontrol.core.connection import DeviceInfo, list_usbmux_devices
        from aircontrol.core.hid import HIDController
        from aircontrol.core.stream import ScreenStreamEngine

        while self._running:
            try:
                target_dev: Optional[DeviceInfo] = None

                # 1. Check for physical USB cable connection
                raw_usb = await list_usbmux_devices()
                usb_serials = [
                    getattr(d, "serial", "") or getattr(d, "udid", "")
                    for d in raw_usb
                    if (getattr(d, "serial", "") or getattr(d, "udid", ""))
                ]

                if self.force_usb:
                    # Explicit --usb CLI mode
                    if usb_serials:
                        chosen_udid = self.udid if (self.udid and self.udid in usb_serials) else usb_serials[0]
                        target_dev = DeviceInfo(udid=chosen_udid, connection_type="usb")
                    else:
                        def _update_usb_waiting_ui():
                            self.window.update_device_status(False)
                            self.window.video_widget.set_status_text(
                                "Chế độ USB: Vui lòng cắm cáp USB vào máy tính..."
                            )
                        QTimer.singleShot(0, _update_usb_waiting_ui)
                        if self._connect_trigger_event is not None:
                            with contextlib.suppress(asyncio.TimeoutError):
                                await asyncio.wait_for(self._connect_trigger_event.wait(), timeout=2.0)
                            self._connect_trigger_event.clear()
                        else:
                            await asyncio.sleep(2.0)
                        continue

                elif not self.force_wifi and usb_serials:
                    # Physical USB cable plugged in: connect via USB immediately (< 0.5s)
                    chosen_udid = self.udid if (self.udid and self.udid in usb_serials) else usb_serials[0]
                    target_dev = DeviceInfo(udid=chosen_udid, connection_type="usb")

                elif self.target_ip:
                    # Direct target IP requested (from CLI --ip or from UI input bar)
                    target_dev = DeviceInfo(
                        udid=self.udid or "wifi-target-ip",
                        name=f"iPhone ({self.target_ip})",
                        connection_type="wifi",
                    )

                elif self.force_wifi and self.udid:
                    # Explicit --wifi and --udid CLI mode
                    target_dev = DeviceInfo(udid=self.udid, connection_type="wifi")

                else:
                    # Default Smart Wireless Mode: Auto-Discovery via Bonjour _remotepairing._tcp
                    target_dev = DeviceInfo(udid=self.udid or "wifi-auto", connection_type="wifi")

                is_wifi = (target_dev.connection_type == "wifi") or bool(self.target_ip and not self.force_usb)

                # Helper to update UI status safely from worker thread
                def on_status_safe(text: str) -> None:
                    QTimer.singleShot(0, lambda: self.window.video_widget.set_status_text(text))

                # 2. Connect to device
                dev_info: DeviceInfo = await self.conn_mgr.connect(
                    udid=target_dev.udid if target_dev.udid != "wifi-target-ip" else (self.udid or None),
                    via_wifi=is_wifi,
                    on_status=on_status_safe,
                    target_ip=self.target_ip,
                )
                display_name = dev_info.marketing_name or dev_info.name or "iPhone"
                ios_raw = dev_info.ios_version or "18.0"
                ios_ver = f"iOS {ios_raw}" if not str(ios_raw).startswith("iOS") else str(ios_raw)
                conn_label = "Wi-Fi" if dev_info.connection_type == "wifi" else "USB"
                logger.info("Connected to %s (%s) over %s", display_name, ios_ver, conn_label)

                # Initialize HID controller
                self.hid_controller = HIDController(rsd=self.conn_mgr.rsd, loop=self.loop)
                self.window.hid_controller = self.hid_controller

                # Initialize PasteboardManager for Unicode typing and bidirectional clipboard sync
                from aircontrol.core.pasteboard import PasteboardManager

                self.pasteboard_mgr = PasteboardManager(rsd=self.conn_mgr.rsd, loop=self.loop)
                try:
                    pb_started = await self.pasteboard_mgr.start()
                    if pb_started:
                        logger.info("iOS PasteboardManager started successfully")
                    else:
                        logger.debug("iOS PasteboardManager start skipped or unsupported")
                except Exception as pb_err:
                    logger.debug("PasteboardManager start error: %s", pb_err)
                self.window.pasteboard_mgr = self.pasteboard_mgr

                # Silence physical iPhone speaker automatically once connection stabilizes
                async def _delayed_mute_speaker() -> None:
                    await asyncio.sleep(0.5)
                    if self.hid_controller:
                        await self.hid_controller.mute_device_speaker()

                self.loop.create_task(_delayed_mute_speaker())

                # Update UI to connected state
                def _update_ui_on_connect(n=display_name, m=ios_ver, c=conn_label):
                    self.window.update_device_status(True, n, m, c)

                QTimer.singleShot(0, _update_ui_on_connect)

                # 3. Start Screen Streaming Engine
                def on_pcm_safe(pcm_bytes: bytes) -> None:
                    if hasattr(self.window, "audio_output") and self.window.audio_output:
                        self.window.audio_output.write_pcm(pcm_bytes)

                self.stream_engine = ScreenStreamEngine(
                    rsd=self.conn_mgr.rsd,
                    on_frame=self.window.video_widget.post_frame,
                    on_yuv_frame=self.window.video_widget.post_frame_yuv,
                    on_pcm=on_pcm_safe,
                    on_status=on_status_safe,
                )

                # Stream runs until disconnected or cancelled
                self._current_stream_task = asyncio.create_task(self.stream_engine.start())
                await self._current_stream_task

            except asyncio.CancelledError:
                break
            except Exception as e:
                err_str = str(e)
                if "9022" in err_str or "microphone or camera" in err_str:
                    logger.warning("Camera or microphone in use on iPhone (Code 9022): %s", e)
                    QTimer.singleShot(
                        0,
                        lambda: self.window.video_widget.set_status_text(
                            "iPhone đang dùng Camera hoặc Micro. Hãy đóng ứng dụng đó trên iPhone."
                        ),
                    )
                elif "displayservice" in err_str.lower() or "developer mode" in err_str.lower():
                    logger.warning("DisplayService hoặc Developer Mode chưa sẵn sàng trên iPhone: %s", e)
                    QTimer.singleShot(
                        0,
                        lambda: self.window.video_widget.set_status_text(
                            "DisplayService chưa sẵn sàng. Hãy mở khóa iPhone và bật 'Chế độ nhà phát triển' trong Cài đặt."
                        ),
                    )
                    await asyncio.sleep(2.5)
                elif "could not reach wi-fi device" in err_str.lower() or "ensure iphone screen is awake" in err_str.lower():
                    logger.debug("Wi-Fi device search cycle: %s", e)
                    QTimer.singleShot(
                        0,
                        lambda: self.window.video_widget.set_status_text(
                            "Đang tìm kiếm iPhone qua Wi-Fi...\nHãy mở sáng màn hình iPhone (cùng mạng Wi-Fi) hoặc cắm cáp USB."
                        ),
                    )
                else:
                    logger.warning("Stream session ended or error: %s", e)
            finally:
                # Clean up current stream and connection before reconnect/idle
                if self.stream_engine:
                    self.stream_engine.stop()
                    self.stream_engine = None
                if self.pasteboard_mgr:
                    await self.pasteboard_mgr.close()
                    self.pasteboard_mgr = None
                if hasattr(self.window, "pasteboard_mgr"):
                    self.window.pasteboard_mgr = None
                if self.hid_controller:
                    await self.hid_controller.close()
                    self.hid_controller = None
                if self.conn_mgr:
                    await self.conn_mgr.disconnect()
                if self._cli_target_ip is None:
                    self.target_ip = None
                QTimer.singleShot(0, lambda: self.window.update_device_status(False, preserve_status=True))

            # Wait for either user trigger (e.g. entered IP / clicked connect) or timeout before next retry
            if self._connect_trigger_event is not None:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._connect_trigger_event.wait(), timeout=2.5)
                self._connect_trigger_event.clear()
            else:
                await asyncio.sleep(2.5)

    def stop(self) -> None:
        """Stop background worker thread and clean up all connections."""
        self._running = False
        if self.stream_engine:
            self.stream_engine.stop()
        if self.pasteboard_mgr and self.loop and self.loop.is_running():
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(self.pasteboard_mgr.close(), self.loop)
        if self.loop and self.loop.is_running():
            if self._current_stream_task and not self._current_stream_task.done():
                self.loop.call_soon_threadsafe(self._current_stream_task.cancel)
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aircontrol - Bespoke 60 FPS iPhone Mirror & Remote Control",
    )
    parser.add_argument("--udid", type=str, default=None, help="Target iPhone UDID")
    parser.add_argument("--usb", action="store_true", default=False, help="Force USB connection only (offline / zero Wi-Fi)")
    parser.add_argument("--wifi", action="store_true", default=False, help="Force Wi-Fi connection only")
    parser.add_argument("--ip", type=str, default=None, help="Target iPhone IP address for direct Wi-Fi connection")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. Hardware double-buffering with V-Sync (tear-free display at 60-120fps)
    surface_fmt = QSurfaceFormat()
    surface_fmt.setSwapInterval(1)
    surface_fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    surface_fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(surface_fmt)

    # Enable fractional High-DPI scaling (crisp rendering on 125%, 150%, 175% Windows displays)
    from PySide6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    # 2. Qt Application initialization
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Aircontrol")
    app.setOrganizationName("Aircontrol")

    # Load application icon for Windows taskbar and system tray
    icon_candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "assets" / "aircontrol.ico",
        Path(sys.executable).parent / "assets" / "aircontrol.ico",
        Path(__file__).parent.parent / "assets" / "aircontrol.ico",
    ]
    for icp in icon_candidates:
        if icp.is_file():
            app.setWindowIcon(QIcon(str(icp)))
            break

    # Single-instance guard: prevent duplicate processes from fighting over ports and tunnels
    socket = QLocalSocket()
    socket.connectToServer("aircontrol_single_instance_lock")
    if socket.waitForConnected(200):
        logger.warning("Another instance of Aircontrol is already running. Exiting.")
        socket.close()
        return 0

    local_server = QLocalServer()
    local_server.removeServer("aircontrol_single_instance_lock")
    local_server.listen("aircontrol_single_instance_lock")

    # Set default Vietnamese font with safe multi-family fallback
    font = QFont()
    font.setFamilies(["Be Vietnam Pro", "Segoe UI Variable Text", "Segoe UI", "Arial", "sans-serif"])
    font.setPointSize(10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    app.setStyleSheet("""
        QToolTip {
            background-color: #1A1D24;
            color: #E2E8F0;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 6px;
            padding: 5px 9px;
            font-size: 11px;
            font-family: 'Be Vietnam Pro', 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
        }
    """)

    # 3. Create Main Window (opens instantaneously)
    from aircontrol.ui.window import AircontrolWindow
    window = AircontrolWindow()
    window.show()

    # 4. Start Background App Runner (Smart Dual-Mode: USB-first with Wi-Fi fallback)
    runner = AircontrolAppRunner(
        window=window,
        udid=args.udid,
        force_usb=args.usb,
        force_wifi=args.wifi,
        target_ip=args.ip,
    )
    runner.start()

    logger.info("Aircontrol Desktop GUI launched successfully.")
    try:
        ret = app.exec()
    finally:
        runner.stop()
        local_server.close()

    return ret


if __name__ == "__main__":
    sys.exit(main())
