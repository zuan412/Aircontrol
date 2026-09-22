"""Floating Acrylic Toolbar for Aircontrol."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AcrylicToolbar(QFrame):
    """Sleek, minimalist floating toolbar with monochrome icons and quick action buttons."""

    screenshot_requested = Signal()
    rotate_requested = Signal()
    audio_toggled = Signal(bool)
    hud_toggled = Signal(bool)
    reconnect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_audio_enabled = False
        self._is_hud_enabled = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("AcrylicToolbar")
        self.setStyleSheet("""
            #AcrylicToolbar {
                background-color: rgba(24, 27, 34, 0.88);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 16px;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 10px;
                color: #e0e0e0;
                font-family: 'Segoe UI', 'Be Vietnam Pro', sans-serif;
                font-size: 11px;
                font-weight: 600;
                padding: 10px 12px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.2);
            }
            QPushButton:checked {
                background-color: rgba(0, 113, 227, 0.35);
                color: #2997ff;
                border: 1px solid rgba(41, 151, 255, 0.4);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(8)

        # 1. Screenshot
        self.btn_screenshot = QPushButton("Chụp Ảnh")
        self.btn_screenshot.setToolTip("Chụp ảnh màn hình iPhone (Ctrl+P)")
        self.btn_screenshot.clicked.connect(self.screenshot_requested.emit)
        layout.addWidget(self.btn_screenshot)

        # 2. Rotate
        self.btn_rotate = QPushButton("Xoay Màn")
        self.btn_rotate.setToolTip("Xoay màn hình 90° (Ctrl+R)")
        self.btn_rotate.clicked.connect(self.rotate_requested.emit)
        layout.addWidget(self.btn_rotate)

        # 3. Sound Toggle
        self.btn_audio = QPushButton("Âm Thanh")
        self.btn_audio.setCheckable(True)
        self.btn_audio.setToolTip("Bật/Tắt âm thanh từ iPhone (Ctrl+M)")
        self.btn_audio.toggled.connect(self.audio_toggled.emit)
        layout.addWidget(self.btn_audio)

        # 4. Telemetry HUD
        self.btn_hud = QPushButton("HUD FPS")
        self.btn_hud.setCheckable(True)
        self.btn_hud.setToolTip("Bật/Tắt hiển thị thông số hiệu năng (Ctrl+I)")
        self.btn_hud.toggled.connect(self.hud_toggled.emit)
        layout.addWidget(self.btn_hud)

        # 5. Reconnect
        self.btn_reconnect = QPushButton("Kết Nối Lại")
        self.btn_reconnect.setToolTip("Làm mới kết nối thiết bị")
        self.btn_reconnect.clicked.connect(self.reconnect_requested.emit)
        layout.addWidget(self.btn_reconnect)

        self.setLayout(layout)
