"""Application lifecycle and System Tray setup for Aircontrol."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from aircontrol.ui.window import AircontrolWindow

logger = logging.getLogger(__name__)


class AircontrolApp:
    """Manages QApplication instance, High-DPI fonts, and system tray."""

    def __init__(self, sys_argv: Optional[list[str]] = None) -> None:
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys_argv or sys.argv)

        self._configure_application()
        self.window: Optional[AircontrolWindow] = None
        self.tray_icon: Optional[QSystemTrayIcon] = None

    def _configure_application(self) -> None:
        self.app.setApplicationName("Aircontrol")
        self.app.setOrganizationName("Aircontrol")

        # Set default font
        font = QFont("Be Vietnam Pro", 10)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        self.app.setFont(font)

    def create_window(
        self,
        stream_url: str = "http://127.0.0.1:8080",
        device_name: str = "iPhone",
        hid_bridge: Optional[object] = None,
    ) -> AircontrolWindow:
        self.window = AircontrolWindow(
            stream_url=stream_url,
            device_name=device_name,
            hid_bridge=hid_bridge,
        )
        self._setup_tray()
        return self.window

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self.app)
        self.tray_icon.setToolTip("Aircontrol - iPhone Mirror & Control")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Hiển Thị Cửa Sổ")
        show_action.triggered.connect(self._show_window)

        hide_action = tray_menu.addAction("Ẩn Xuống Khay")
        hide_action.triggered.connect(self._hide_window)

        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Thoát Aircontrol")
        quit_action.triggered.connect(self.app.quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_window(self) -> None:
        if self.window:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def _hide_window(self) -> None:
        if self.window:
            self.window.hide()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.window and self.window.isVisible():
                self._hide_window()
            else:
                self._show_window()

    def run(self) -> int:
        if self.window:
            self.window.show()
        return self.app.exec()
