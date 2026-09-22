"""AircontrolWindow: Bespoke Desktop Window housing the iPhone frame and Acrylic toolbar."""

from __future__ import annotations

import logging
from typing import Any, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QWidget,
)

from aircontrol.ui.toolbar import AcrylicToolbar
from aircontrol.ui.webcodecs_view import WebCodecsView

logger = logging.getLogger(__name__)


class AircontrolWindow(QMainWindow):
    """Main desktop application window for Aircontrol."""

    def __init__(
        self,
        stream_url: str = "http://127.0.0.1:8080",
        device_name: str = "iPhone 16 Pro",
        hid_bridge: Any = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.stream_url = stream_url
        self.device_name = device_name
        self.hid_bridge = hid_bridge

        self.setWindowTitle(f"Aircontrol - {self.device_name}")
        self.resize(560, 920)
        self.setMinimumSize(400, 700)

        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self) -> None:
        # Dark bespoke palette
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0b0d11;
            }
            QStatusBar {
                background-color: #12151b;
                color: #86868b;
                font-family: 'Segoe UI', 'Be Vietnam Pro', sans-serif;
                font-size: 11px;
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
        """)

        # Central container
        central_widget = QWidget(self)
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        # WebCodecs Viewport
        self.viewport = WebCodecsView(url=self.stream_url, parent=central_widget)
        layout.addWidget(self.viewport, stretch=1)

        # Acrylic Toolbar
        self.toolbar = AcrylicToolbar(parent=central_widget)
        layout.addWidget(self.toolbar, stretch=0, alignment=Qt.AlignmentFlag.AlignTop)

        self.setCentralWidget(central_widget)

        # Status Bar
        status_bar = QStatusBar(self)
        self.status_label = QLabel(f"Thiết bị: {self.device_name} | Sẵn sàng")
        status_bar.addWidget(self.status_label)
        self.setStatusBar(status_bar)

        # Connect toolbar signals
        self.toolbar.screenshot_requested.connect(self._on_screenshot)
        self.toolbar.rotate_requested.connect(self._on_rotate)
        self.toolbar.hud_toggled.connect(self._on_hud_toggle)
        self.toolbar.audio_toggled.connect(self._on_audio_toggle)

    def _setup_shortcuts(self) -> None:
        # Ctrl+H: Home
        action_home = QAction(self)
        action_home.setShortcut(QKeySequence("Ctrl+H"))
        action_home.triggered.connect(lambda: self._trigger_button("home"))
        self.addAction(action_home)

        # Ctrl+L: Lock/Power
        action_lock = QAction(self)
        action_lock.setShortcut(QKeySequence("Ctrl+L"))
        action_lock.triggered.connect(lambda: self._trigger_button("power"))
        self.addAction(action_lock)

        # Ctrl+P: Screenshot
        action_screenshot = QAction(self)
        action_screenshot.setShortcut(QKeySequence("Ctrl+P"))
        action_screenshot.triggered.connect(self._on_screenshot)
        self.addAction(action_screenshot)

        # Ctrl+R: Rotate
        action_rotate = QAction(self)
        action_rotate.setShortcut(QKeySequence("Ctrl+R"))
        action_rotate.triggered.connect(self._on_rotate)
        self.addAction(action_rotate)

    def _trigger_button(self, name: str) -> None:
        if self.hid_bridge:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.hid_bridge.send_button(name))
            except RuntimeError:
                pass
        self.status_label.setText(f"Phím cứng: {name.upper()}")

    def _on_screenshot(self) -> None:
        self.status_label.setText("Đang chụp ảnh màn hình...")
        if self.viewport:
            # Execute JS screenshot trigger or capture page
            self.viewport.page().runJavaScript("if (typeof takeScreenshot === 'function') takeScreenshot();")

    def _on_rotate(self) -> None:
        self.status_label.setText("Đang xoay màn hình thiết bị...")
        self._trigger_button("rotate")

    def _on_hud_toggle(self, enabled: bool) -> None:
        self.status_label.setText(f"HUD FPS: {'Bật' if enabled else 'Tắt'}")
        hidden_val = "false" if enabled else "true"
        if self.viewport:
            self.viewport.page().runJavaScript(
                f"const h = document.getElementById('telemetry-hud'); if(h) h.classList.toggle('hidden', {hidden_val});"
            )

    def _on_audio_toggle(self, enabled: bool) -> None:
        self.status_label.setText(f"Âm thanh: {'Bật' if enabled else 'Tắt'}")
