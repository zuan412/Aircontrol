"""Aircontrol bespoke desktop application window housing the Apple Simulator iPhone view."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
import sys
from typing import Any, Callable, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Slot
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QMouseEvent, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from aircontrol.ui.simulator_titlebar import SimulatorTitleBar
from aircontrol.ui.skin_engine import SkinManager, SkinProfile
from aircontrol.ui.video_widget import VideoWidget

logger = logging.getLogger(__name__)


class AircontrolWindow(QMainWindow):
    """Bespoke Apple Xcode Simulator style desktop window for iPhone mirroring."""

    _RESIZE_BORDER_WIDTH = 8

    def __init__(
        self,
        device_name: str = "iPhone",
        hid_controller: Any = None,
        on_rotate_request: Optional[Callable[[], None]] = None,
        on_reconnect_request: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.device_name = device_name
        self.hid_controller = hid_controller
        self.pasteboard_mgr: Optional[Any] = None
        self.on_rotate_request = on_rotate_request
        self.on_reconnect_request = on_reconnect_request

        self.setWindowTitle(f"Aircontrol - {self.device_name}")
        self.setMinimumSize(240, 480)

        # Frameless window for authentic macOS Simulator feel
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        # Window state
        self.is_borderless: bool = False
        self.is_always_on_top: bool = False
        self._resize_edge: Optional[str] = None
        self._drag_start_pos: Optional[QPoint] = None
        self._drag_start_geometry: Optional[QRect] = None
        self._drag_pos: Optional[QPoint] = None
        self._has_snapped_aspect: bool = False
        self._has_shown: bool = False

        # Skin Engine
        self.skin_manager = SkinManager()
        self.current_skin: SkinProfile = self.skin_manager.active_skin

        # Low-latency system audio output through laptop speakers
        from aircontrol.ui.audio_output import AudioOutputManager
        self.audio_output = AudioOutputManager(self)

        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._center_on_screen()

    def _setup_ui(self) -> None:
        central_widget = QWidget(self)
        central_widget.setObjectName("CentralWidget")
        central_widget.setStyleSheet("""
            QWidget#CentralWidget {
                background-color: #121418;
            }
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
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. macOS Simulator Custom Title Bar
        self.title_bar = SimulatorTitleBar(device_name=self.device_name, parent=self)
        self.title_bar.setup_skins_menu(self.skin_manager.available_skins, self.current_skin.id)
        # Compatibility alias for existing tests
        self.toolbar = self.title_bar
        main_layout.addWidget(self.title_bar, stretch=0)

        # 2. Pure Edge-to-Edge iPhone Surface
        self.video_widget = VideoWidget(central_widget)
        self.video_widget.apply_skin(self.current_skin)
        self.video_widget.on_fps_update = self._on_fps_updated
        self.video_widget.installEventFilter(self)
        main_layout.addWidget(self.video_widget, stretch=1)

        self.setCentralWidget(central_widget)

    def _calc_window_width(self, height: int, aspect: Optional[float] = None) -> int:
        """Calculate exact window width so iPhone screen hugs the window with zero letterboxing."""
        if aspect is None:
            if hasattr(self, "current_skin") and self.current_skin:
                aspect = self.current_skin.aspect_ratio
            elif hasattr(self, "video_widget") and hasattr(self.video_widget, "get_aspect_ratio"):
                aspect = self.video_widget.get_aspect_ratio()
            else:
                aspect = 9.0 / 19.5
        titlebar_h = self.title_bar.height() if (hasattr(self, "title_bar") and self.title_bar.isVisible()) else 0
        bezel = self.video_widget.bezel_width if hasattr(self, "video_widget") else 0.0
        vh = max(50.0, float(height - titlebar_h - 2.0 * bezel))
        vw = vh * aspect
        return max(self.minimumWidth(), int(round(vw + 2.0 * bezel)))

    def _calc_window_height(self, width: int, aspect: Optional[float] = None) -> int:
        """Calculate exact window height matching width to preserve iPhone body proportions."""
        if aspect is None:
            if hasattr(self, "current_skin") and self.current_skin:
                aspect = self.current_skin.aspect_ratio
            elif hasattr(self, "video_widget") and hasattr(self.video_widget, "get_aspect_ratio"):
                aspect = self.video_widget.get_aspect_ratio()
            else:
                aspect = 9.0 / 19.5
        titlebar_h = self.title_bar.height() if (hasattr(self, "title_bar") and self.title_bar.isVisible()) else 0
        bezel = self.video_widget.bezel_width if hasattr(self, "video_widget") else 0.0
        vw = max(50.0, float(width - 2.0 * bezel))
        vh = vw / aspect
        return max(self.minimumHeight(), int(round(vh + 2.0 * bezel + titlebar_h)))

    def _center_on_screen(self, height_ratio: float = 0.70) -> None:
        """Fit window tightly to iPhone body proportions and center on active desktop display."""
        screen = QApplication.primaryScreen()
        if not screen:
            self.resize(330, 715)
            return
        geo = screen.availableGeometry()
        # Compact and ergonomic: ~710px on 1080p, fits cleanly alongside code/browser
        target_h = max(640, min(geo.height() - 40, int(geo.height() * height_ratio)))
        target_w = self._calc_window_width(target_h)

        self.resize(target_w, target_h)
        center_x = geo.x() + (geo.width() - target_w) // 2
        center_y = geo.y() + (geo.height() - target_h) // 2
        self.move(center_x, center_y)

    def _apply_win11_dwm_style(self) -> None:
        """Apply native Windows 11 hardware-accelerated anti-aliased rounded corners and border."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes, c_int, byref
            hwnd = int(self.winId())
            dwmapi = ctypes.WinDLL("dwmapi")
            # 33 = DWMWA_WINDOW_CORNER_PREFERENCE, 2 = DWMWCP_ROUND (Windows 11 standard rounded corners)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(33),
                byref(c_int(2)),
                ctypes.sizeof(c_int),
            )
            # 34 = DWMWA_BORDER_COLOR: subtle dark titanium #2E333D (BGR: 0x003D332E)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(34),
                byref(c_int(0x003D332E)),
                ctypes.sizeof(c_int),
            )
        except Exception as e:
            logger.debug("DWM styling: %s", e)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._has_shown:
            self._has_shown = True
            self._center_on_screen()
        self._apply_win11_dwm_style()

    def changeEvent(self, event) -> None:
        if event.type() == event.Type.WindowStateChange:
            if self.isMaximized():
                # Intercept maximize event: prevent full-screen black void and restore centered frame
                self.showNormal()
                self._center_on_screen()
        elif event.type() == event.Type.ActivationChange:
            if not self.isActiveWindow():
                self._handle_focus_loss()
            else:
                self._update_keyboard_indicator(True)
        super().changeEvent(event)

    def _connect_signals(self) -> None:
        # VideoWidget input -> HID Controller
        self.video_widget.on_touch = self._handle_touch
        self.video_widget.on_multi_touch = self._handle_multi_touch
        self.video_widget.on_scroll = self._handle_scroll
        self.video_widget.on_zoom = self._handle_zoom
        self.video_widget.on_home = lambda: self._trigger_button("home")
        self.video_widget.on_app_switcher = self._handle_app_switcher
        self.video_widget.on_unlock_swipe = self._handle_unlock_swipe
        self.video_widget.on_key = self._handle_key
        self.video_widget.on_focus_loss = self._handle_focus_loss
        self.video_widget.on_text = self._handle_text
        self.video_widget.on_paste = self.paste_clipboard_to_phone

        # Title bar traffic lights
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_maximize)

        # Title bar action buttons
        self.title_bar.audio_toggle_requested.connect(self.toggle_audio)
        self.audio_output.mute_changed.connect(self.title_bar.set_audio_state)
        self.title_bar.keyboard_toggle_requested.connect(self._toggle_keyboard)
        self.title_bar.home_requested.connect(lambda: self._trigger_button("home"))
        self.title_bar.app_switcher_requested.connect(self._handle_app_switcher)
        self.title_bar.screenshot_requested.connect(self._on_screenshot)
        self.title_bar.rotate_requested.connect(self._on_rotate)
        self.title_bar.lock_requested.connect(lambda: self._trigger_button("lock"))
        self.title_bar.borderless_requested.connect(self.toggle_borderless)
        self.title_bar.dim_screen_requested.connect(self._toggle_dim_screen)
        self.title_bar.always_on_top_requested.connect(self.toggle_always_on_top)
        self.title_bar.open_screenshots_requested.connect(self.open_screenshots_folder)
        self.title_bar.paste_clipboard_requested.connect(self.paste_clipboard_to_phone)

        # Title bar skin selection & dynamic switching
        self.title_bar.skin_selected.connect(self.set_skin)
        self.skin_manager.skin_changed.connect(self._on_skin_changed)

    def _setup_shortcuts(self) -> None:
        # Ctrl+T: Toggle Always on Top (Stay on top of all windows)
        act_pin = QAction(self)
        act_pin.setShortcut(QKeySequence("Ctrl+T"))
        act_pin.triggered.connect(self.toggle_always_on_top)
        self.addAction(act_pin)

        # Ctrl+Shift+V: Paste text from Windows Clipboard into iPhone
        act_paste = QAction(self)
        act_paste.setShortcut(QKeySequence("Ctrl+Shift+V"))
        act_paste.triggered.connect(self.paste_clipboard_to_phone)
        self.addAction(act_paste)

        # Ctrl+B: Toggle Borderless Mode (Chassis Model vs Pure Floating Display)
        act_borderless = QAction(self)
        act_borderless.setShortcut(QKeySequence("Ctrl+B"))
        act_borderless.triggered.connect(self.toggle_borderless)
        self.addAction(act_borderless)

        # Ctrl+W: Close Window
        act_close = QAction(self)
        act_close.setShortcut(QKeySequence("Ctrl+W"))
        act_close.triggered.connect(self.close)
        self.addAction(act_close)

        # Ctrl+M: Minimize Window
        act_min = QAction(self)
        act_min.setShortcut(QKeySequence("Ctrl+M"))
        act_min.triggered.connect(self.showMinimized)
        self.addAction(act_min)

        # Ctrl+Shift+M: Mute / Restore Physical iPhone Speaker
        act_mute_phone = QAction(self)
        act_mute_phone.setShortcut(QKeySequence("Ctrl+Shift+M"))
        act_mute_phone.triggered.connect(self._toggle_phone_speaker)
        self.addAction(act_mute_phone)

        # Ctrl+Shift+D: Dim / Restore Physical iPhone Display (Standby Mode)
        act_dim_screen = QAction(self)
        act_dim_screen.setShortcut(QKeySequence("Ctrl+Shift+D"))
        act_dim_screen.triggered.connect(self._toggle_dim_screen)
        self.addAction(act_dim_screen)

        # Ctrl+U: Unlock (Swipe Up)
        act_unlock = QAction(self)
        act_unlock.setShortcut(QKeySequence("Ctrl+U"))
        act_unlock.triggered.connect(self._handle_unlock_swipe)
        self.addAction(act_unlock)

        # Home Screen: Win / Home / Esc / Ctrl+1 / Ctrl+H
        act_home = QAction(self)
        act_home.setShortcuts([
            QKeySequence(Qt.Key.Key_Home),
            QKeySequence("Home"),
            QKeySequence("Ctrl+1"),
            QKeySequence("Ctrl+H"),
            QKeySequence(Qt.Key.Key_Escape),
            QKeySequence("Esc"),
        ])
        act_home.triggered.connect(lambda: self._trigger_button("home"))
        self.addAction(act_home)

        # App Switcher: Alt+Tab / Ctrl+Tab / Ctrl+2
        act_switcher = QAction(self)
        act_switcher.setShortcuts([
            QKeySequence("Ctrl+Tab"),
            QKeySequence("Alt+Tab"),
            QKeySequence("Ctrl+2"),
        ])
        act_switcher.triggered.connect(self._handle_app_switcher)
        self.addAction(act_switcher)

        # Ctrl+= or Ctrl++: Two-Finger Pinch Zoom In
        act_zoom_in = QAction(self)
        act_zoom_in.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        act_zoom_in.triggered.connect(lambda: self._handle_zoom(True, 32768, 32768))
        self.addAction(act_zoom_in)

        # Ctrl+-: Two-Finger Pinch Zoom Out
        act_zoom_out = QAction(self)
        act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        act_zoom_out.triggered.connect(lambda: self._handle_zoom(False, 32768, 32768))
        self.addAction(act_zoom_out)

        # Ctrl+0: Reset Zoom (Double tap center)
        act_zoom_reset = QAction(self)
        act_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        act_zoom_reset.triggered.connect(lambda: self._trigger_double_tap(32768, 32768))
        self.addAction(act_zoom_reset)

        # PageUp / PageDown: Smooth Inertial Scroll
        act_pgup = QAction(self)
        act_pgup.setShortcut(QKeySequence(Qt.Key.Key_PageUp))
        act_pgup.triggered.connect(lambda: self._handle_scroll(True, 32768, 32768, False))
        self.addAction(act_pgup)

        act_pgdn = QAction(self)
        act_pgdn.setShortcut(QKeySequence(Qt.Key.Key_PageDown))
        act_pgdn.triggered.connect(lambda: self._handle_scroll(False, 32768, 32768, False))
        self.addAction(act_pgdn)

        # Ctrl+L: Lock iPhone / Power
        act_lock = QAction(self)
        act_lock.setShortcut(QKeySequence("Ctrl+L"))
        act_lock.triggered.connect(lambda: self._trigger_button("lock"))
        self.addAction(act_lock)

        # F12 / Ctrl+P: Screenshot
        act_screenshot = QAction(self)
        act_screenshot.setShortcuts([
            QKeySequence("Ctrl+P"),
            QKeySequence("F12"),
            QKeySequence(Qt.Key.Key_F12),
        ])
        act_screenshot.triggered.connect(self._on_screenshot)
        self.addAction(act_screenshot)

        # Ctrl+R: Rotate
        act_rotate = QAction(self)
        act_rotate.setShortcut(QKeySequence("Ctrl+R"))
        act_rotate.triggered.connect(self._on_rotate)
        self.addAction(act_rotate)

        # Volume Up / Down
        act_vol_up = QAction(self)
        act_vol_up.setShortcut(QKeySequence("Ctrl+Up"))
        act_vol_up.triggered.connect(lambda: self._trigger_button("volume-up"))
        self.addAction(act_vol_up)

        act_vol_down = QAction(self)
        act_vol_down.setShortcut(QKeySequence("Ctrl+Down"))
        act_vol_down.triggered.connect(lambda: self._trigger_button("volume-down"))
        self.addAction(act_vol_down)

        # Dynamic Scale Shortcuts: Ctrl+= / Ctrl++ (Zoom In), Ctrl+- (Zoom Out), Ctrl+0 (Reset)
        act_zoom_in = QAction(self)
        act_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        act_zoom_in.triggered.connect(lambda: self._adjust_scale(1.15))
        self.addAction(act_zoom_in)

        act_zoom_out = QAction(self)
        act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        act_zoom_out.triggered.connect(lambda: self._adjust_scale(0.87))
        self.addAction(act_zoom_out)

        act_zoom_reset = QAction(self)
        act_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        act_zoom_reset.triggered.connect(self._center_on_screen)
        self.addAction(act_zoom_reset)

    def _adjust_scale(self, factor: float) -> None:
        """Dynamically scale the window larger or smaller for comfortable reading of fine text."""
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        new_h = int(round(self.height() * factor))
        new_h = max(480, min(geo.height() - 30, new_h))
        new_w = self._calc_window_width(new_h)

        old_center_x = self.x() + self.width() // 2
        old_center_y = self.y() + self.height() // 2

        self.resize(new_w, new_h)
        self.move(
            max(geo.x(), min(geo.x() + geo.width() - new_w, old_center_x - new_w // 2)),
            max(geo.y(), min(geo.y() + geo.height() - new_h, old_center_y - new_h // 2)),
        )

    def toggle_borderless(self) -> None:
        """Toggle titlebar visibility for immersive full-bleed display."""
        self.is_borderless = not self.is_borderless

        if self.is_borderless:
            self.video_widget.bezel_width = 0.0
            self.title_bar.hide()
        else:
            self.video_widget.bezel_width = self.current_skin.bezel_width if hasattr(self, "current_skin") else 0.0
            self.title_bar.show()

        old_center_x = self.x() + self.width() // 2
        old_center_y = self.y() + self.height() // 2

        target_w = self._calc_window_width(self.height())
        target_h = self._calc_window_height(target_w)

        self.resize(target_w, target_h)
        self.move(old_center_x - target_w // 2, old_center_y - target_h // 2)

        self.video_widget.update()
        self._apply_win11_dwm_style()

    def set_skin(self, skin_id: str) -> None:
        """Switch current device skin and refresh layout accordingly."""
        skin = self.skin_manager.set_active_skin(skin_id)
        if skin:
            self._on_skin_changed(skin)

    def _on_skin_changed(self, skin: SkinProfile) -> None:
        """Handle skin profile update: re-skin video widget, update titlebar, snug fit."""
        self.current_skin = skin
        self.video_widget.apply_skin(skin)
        self.title_bar.setup_skins_menu(self.skin_manager.available_skins, skin.id)

        # Snug fit window to new aspect ratio
        aspect = skin.aspect_ratio
        target_w = self._calc_window_width(self.height(), aspect=aspect)
        target_h = self._calc_window_height(target_w, aspect=aspect)
        self.resize(target_w, target_h)
        self.video_widget.update()

    def _toggle_zoom(self) -> None:
        """Toggle between large fit view and standard compact view without full-screen void."""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        max_h = int(geo.height() * 0.85)
        std_h = int(geo.height() * 0.68)

        target_h = std_h if abs(self.height() - max_h) < 20 else max_h
        target_w = self._calc_window_width(target_h)

        old_center_x = self.x() + self.width() // 2
        old_center_y = self.y() + self.height() // 2

        self.resize(target_w, target_h)
        self.move(
            max(geo.x(), min(geo.x() + geo.width() - target_w, old_center_x - target_w // 2)),
            max(geo.y(), min(geo.y() + geo.height() - target_h, old_center_y - target_h // 2)),
        )

    def _toggle_maximize(self) -> None:
        self._toggle_zoom()

    def update_device_status(
        self,
        connected: bool,
        name: str = "iPhone",
        model: str = "iOS",
        conn_type: str = "Wi-Fi",
        preserve_status: bool = False,
    ) -> None:
        """Update window state on device connection or disconnection."""
        if connected:
            self.device_name = f"{name}"
            self.setWindowTitle(f"Aircontrol - {self.device_name}")
            self.title_bar.set_device_info(title=name, subtitle=f"{model} • {conn_type} • Sẵn sàng")
            if not preserve_status:
                self.video_widget.set_status_text(f"Đã kết nối {name} ({conn_type}). Đang tải luồng...")
        else:
            self.device_name = "iPhone"
            self.setWindowTitle("Aircontrol - Chờ kết nối iPhone")
            self.title_bar.set_device_info(title="iPhone", subtitle="Chờ kết nối (Wi-Fi / USB)...")
            if not preserve_status:
                self.video_widget.set_status_text("Sẵn sàng kết nối iPhone qua Wi-Fi hoặc cáp USB")

    def _on_fps_updated(self, fps: int, width: int, height: int) -> None:
        self.title_bar.set_telemetry(fps=fps, width=width, height=height)
        if not self._has_snapped_aspect and self.video_widget._frame_width > 0 and self.video_widget._frame_height > 0:
            self._has_snapped_aspect = True
            aspect = self.video_widget.get_aspect_ratio()
            target_w = self._calc_window_width(self.height(), aspect=aspect)
            target_h = self._calc_window_height(target_w, aspect=aspect)
            if abs(self.width() - target_w) > 2 or abs(self.height() - target_h) > 2:
                old_center_x = self.x() + self.width() // 2
                old_center_y = self.y() + self.height() // 2
                self.resize(target_w, target_h)
                self.move(old_center_x - target_w // 2, old_center_y - target_h // 2)

    def _handle_touch(self, touch_type: str, norm_x: int, norm_y: int) -> None:
        if self.hid_controller:
            self.hid_controller.send_touch_sync(touch_type, norm_x, norm_y)

    def _handle_multi_touch(self, contacts: list[tuple[int, int, int, str]]) -> None:
        if self.hid_controller:
            self.hid_controller.send_multi_touch_sync(contacts)

    def _handle_scroll(
        self,
        scroll_up: bool,
        norm_x: int,
        norm_y: int,
        is_horizontal: bool = False,
    ) -> None:
        if self.hid_controller:
            self.hid_controller.send_scroll_swipe_sync(norm_x, norm_y, scroll_up, is_horizontal)

    def _handle_zoom(self, zoom_in: bool, norm_x: int, norm_y: int) -> None:
        if self.hid_controller:
            self.hid_controller.send_zoom_sync(norm_x, norm_y, zoom_in)

    def _trigger_double_tap(self, norm_x: int = 32768, norm_y: int = 32768) -> None:
        if self.hid_controller:
            self.hid_controller.send_double_tap_sync(norm_x, norm_y)

    def _handle_unlock_swipe(self) -> None:
        if self.hid_controller:
            self.hid_controller.send_unlock_swipe_sync()

    def _handle_app_switcher(self) -> None:
        if self.hid_controller:
            self.hid_controller.send_app_switcher_sync()

    def _trigger_button(self, name: str) -> None:
        if self.hid_controller:
            if name == "home":
                self.hid_controller.send_home_sync()
            else:
                self.hid_controller.send_button_sync(name)

    def toggle_audio(self) -> None:
        """Toggle mute/unmute of iPhone audio streaming on laptop speakers."""
        if hasattr(self, "audio_output") and self.audio_output:
            self.audio_output.toggle_mute()

    def _toggle_phone_speaker(self) -> None:
        """Toggle physical iPhone speaker mute/unmute."""
        if self.hid_controller:
            if getattr(self.hid_controller, "_muted_speaker_steps", 0) > 0:
                self.hid_controller.restore_device_speaker_sync()
            else:
                self.hid_controller.mute_device_speaker_sync()

    def _toggle_dim_screen(self) -> None:
        """Toggle physical iPhone display dimming to 0% (blackout sleep) or restore brightness."""
        if self.hid_controller:
            if getattr(self.hid_controller, "_dimmed_screen_steps", 0) > 0:
                self.hid_controller.restore_device_screen_sync()
                if hasattr(self, "title_bar") and hasattr(self.title_bar, "btn_dim"):
                    self.title_bar.btn_dim.is_active = False
                    self.title_bar.btn_dim.update()
            else:
                self.hid_controller.dim_device_screen_sync()
                if hasattr(self, "title_bar") and hasattr(self.title_bar, "btn_dim"):
                    self.title_bar.btn_dim.is_active = True
                    self.title_bar.btn_dim.update()

    def _toggle_keyboard(self) -> None:
        """Toggle keyboard focus on the video widget."""
        if self.video_widget.hasFocus():
            self.clearFocus()
            self._handle_focus_loss()
        else:
            self.video_widget.setFocus()
            self._update_keyboard_indicator(True)

    def _update_keyboard_indicator(self, active: bool) -> None:
        if hasattr(self, "title_bar") and hasattr(self.title_bar, "btn_keyboard"):
            self.title_bar.btn_keyboard.is_active = active
            self.title_bar.btn_keyboard.update()

    def _handle_key(self, usage_code: int, is_down: bool) -> None:
        self._update_keyboard_indicator(True)
        if self.hid_controller:
            self.hid_controller.send_key_sync(usage_code, is_down)

    def _handle_focus_loss(self) -> None:
        self._update_keyboard_indicator(False)
        if self.hid_controller:
            self.hid_controller.release_all_keys_sync()

    def _handle_text(self, text: str) -> None:
        self._update_keyboard_indicator(True)
        if self.hid_controller:
            if hasattr(self.hid_controller, "send_unicode_text_sync"):
                self.hid_controller.send_unicode_text_sync(text, self.pasteboard_mgr)
            else:
                self.hid_controller.send_ascii_text_sync(text)

    def _on_screenshot(self) -> None:
        frame_img = self.video_widget.grabFramebuffer() if hasattr(self.video_widget, "grabFramebuffer") else None
        if frame_img is None or frame_img.isNull():
            frame_img = self.video_widget._image

        if frame_img and not frame_img.isNull():
            screenshots_dir = Path("screenshots").resolve()
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = screenshots_dir / f"iPhone_screenshot_{timestamp}.png"
            frame_img.save(str(save_path), "PNG")
            logger.info("Screenshot saved: %s", save_path)

            # Copy image directly to Windows Clipboard for instant paste into chat apps
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setImage(frame_img)
                logger.info("Screenshot copied to Windows clipboard")

    def toggle_always_on_top(self) -> None:
        """Toggle staying on top of all other desktop windows (Ctrl+T)."""
        self.is_always_on_top = not self.is_always_on_top
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_always_on_top)
        self.show()
        state_str = "Bật" if self.is_always_on_top else "Tắt"
        logger.info("Always on Top: %s", state_str)

    def open_screenshots_folder(self) -> None:
        """Open the local screenshots directory in the system file manager."""
        folder = Path("screenshots").resolve()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                import os
                os.startfile(folder)
            else:
                import subprocess
                subprocess.run(["xdg-open", str(folder)], check=False)
        except Exception as e:
            logger.warning("Failed to open screenshots folder: %s", e)

    def paste_clipboard_to_phone(self) -> None:
        """Read text from Windows Clipboard and paste it into the iPhone (Ctrl+Shift+V / Ctrl+V)."""
        clipboard = QApplication.clipboard()
        if not clipboard:
            return
        text = clipboard.text()
        if not text:
            return

        self._update_keyboard_indicator(True)
        if self.pasteboard_mgr and self.hid_controller:
            self.pasteboard_mgr.send_text_with_paste_sync(text, self.hid_controller)
            logger.info("Pasted %d Unicode characters from Windows clipboard into iPhone via Pasteboard", len(text))
        elif self.hid_controller:
            if not text.isascii() and hasattr(self.hid_controller, "send_unicode_text_sync"):
                self.hid_controller.send_unicode_text_sync(text, self.pasteboard_mgr)
            else:
                self.hid_controller.send_ascii_text_sync(text)
            logger.info("Pasted %d characters from Windows clipboard into iPhone", len(text))

    @Slot()
    def sync_to_stream_aspect(self) -> None:
        """Auto-snap window dimensions to hug the stream when first frame arrives."""
        aspect = self.video_widget.get_aspect_ratio()
        target_w = self._calc_window_width(self.height(), aspect=aspect)
        if abs(target_w - self.width()) > 2:
            self.resize(target_w, self.height())

    def set_orientation(self, angle: int) -> None:
        """Switch window between Portrait (0) and Landscape (270 / 90)."""
        is_landscape = angle in (90, 270)
        self.video_widget.set_orientation(is_landscape)

        aspect = self.video_widget.get_aspect_ratio()
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        if is_landscape:
            # Landscape orientation: widescreen window
            target_h = max(360, min(int(geo.height() * 0.70), 650))
            target_w = self._calc_window_width(target_h, aspect=aspect)
            if target_w > geo.width() - 40:
                target_w = geo.width() - 40
                target_h = self._calc_window_height(target_w, aspect=aspect)
            self.setMinimumSize(420, 260)
        else:
            # Portrait orientation
            target_h = max(520, min(geo.height() - 20, int(geo.height() * 0.70)))
            target_w = self._calc_window_width(target_h, aspect=aspect)
            self.setMinimumSize(240, 480)

        old_center_x = self.x() + self.width() // 2
        old_center_y = self.y() + self.height() // 2

        self.resize(target_w, target_h)
        new_x = max(geo.x(), min(geo.x() + geo.width() - target_w, old_center_x - target_w // 2))
        new_y = max(geo.y(), min(geo.y() + geo.height() - target_h, old_center_y - target_h // 2))
        self.move(new_x, new_y)

        self._apply_win11_dwm_style()

    def _on_rotate(self) -> None:
        """Toggle orientation between Portrait and Landscape on user action (Ctrl+R / Button)."""
        if not self.video_widget.is_landscape:
            self.set_orientation(270)
        else:
            self.set_orientation(0)
        if self.on_rotate_request:
            self.on_rotate_request()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched == getattr(self, "video_widget", None):
            ev_type = event.type()
            if ev_type == QEvent.Type.MouseMove:
                if self._resize_edge and self._drag_start_pos and self._drag_start_geometry:
                    self.mouseMoveEvent(event)
                    return True
                pos_in_win = self.mapFromGlobal(event.globalPosition().toPoint())
                edge = self._get_resize_edge(pos_in_win)
                if edge == "corner":
                    self.video_widget.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif edge == "right":
                    self.video_widget.setCursor(Qt.CursorShape.SizeHorCursor)
                elif edge == "bottom":
                    self.video_widget.setCursor(Qt.CursorShape.SizeVerCursor)
                else:
                    self.video_widget.setCursor(Qt.CursorShape.ArrowCursor)
            elif ev_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                pos_in_win = self.mapFromGlobal(event.globalPosition().toPoint())
                edge = self._get_resize_edge(pos_in_win)
                if edge:
                    if hasattr(self, "video_widget") and self.video_widget:
                        pos_in_vw = self.video_widget.mapFrom(self, pos_in_win)
                        if self.video_widget._is_in_home_zone(pos_in_vw):
                            return False
                    self._resize_edge = edge
                    self._drag_start_pos = event.globalPosition().toPoint()
                    self._drag_start_geometry = self.geometry()
                    return True
            elif ev_type == QEvent.Type.MouseButtonRelease:
                if self._resize_edge:
                    self._resize_edge = None
                    self._drag_start_pos = None
                    self._drag_start_geometry = None
                    return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._get_resize_edge(event.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_start_geometry = self.geometry()
                event.accept()
                return
            if self.is_borderless and (event.modifiers() & Qt.KeyboardModifier.AltModifier):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return

        pos = event.position().toPoint()
        if self._resize_edge and self._drag_start_pos and self._drag_start_geometry:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            geom = QRect(self._drag_start_geometry)
            start_w = self._drag_start_geometry.width()
            start_h = self._drag_start_geometry.height()

            aspect = self.video_widget.get_aspect_ratio() if hasattr(self, "video_widget") else (9.0 / 19.5)

            # Snug-fit resizing to preserve iPhone aspect ratio without black bars and without auto-rotation
            if self._resize_edge == "right":
                new_w = max(self.minimumWidth(), start_w + delta.x())
                new_h = self._calc_window_height(new_w, aspect=aspect)
            elif self._resize_edge == "bottom":
                new_h = max(self.minimumHeight(), start_h + delta.y())
                new_w = self._calc_window_width(new_h, aspect=aspect)
            else:  # "corner"
                if abs(delta.x()) > abs(delta.y()) * 1.2:
                    new_w = max(self.minimumWidth(), start_w + delta.x())
                    new_h = self._calc_window_height(new_w, aspect=aspect)
                else:
                    new_h = max(self.minimumHeight(), start_h + delta.y())
                    new_w = self._calc_window_width(new_h, aspect=aspect)

            screen = self.screen() or QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                new_w = min(geo.width() - 30, new_w)
                new_h = min(geo.height() - 30, new_h)

            geom.setSize(QSize(new_w, new_h))
            self.setGeometry(geom)
            event.accept()
            return

        # Update cursor on border hover
        edge = self._get_resize_edge(pos)
        if edge == "corner":
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge == "right":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge == "bottom":
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._resize_edge = None
        self._drag_start_pos = None
        self._drag_start_geometry = None
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _get_resize_edge(self, pos: QPoint) -> Optional[str]:
        w, h = self.width(), self.height()
        b = self._RESIZE_BORDER_WIDTH
        c = 16  # Corner hit box size
        if (pos.x() >= w - c) and (pos.y() >= h - c):
            return "corner"
        if pos.x() >= w - b:
            return "right"
        if pos.y() >= h - b:
            return "bottom"
        return None

    def closeEvent(self, event) -> None:
        if hasattr(self, "pasteboard_mgr") and self.pasteboard_mgr:
            self.pasteboard_mgr.close_sync()
            self.pasteboard_mgr = None
        if hasattr(self, "hid_controller") and self.hid_controller:
            if getattr(self.hid_controller, "_dimmed_screen_steps", 0) > 0:
                self.hid_controller.restore_device_screen_sync()
        if hasattr(self, "audio_output") and self.audio_output:
            self.audio_output.close()
        if hasattr(self, "video_widget") and self.video_widget:
            self.video_widget.cleanupGL()
        super().closeEvent(event)


# Compatibility alias for architecture naming
MainWindow = AircontrolWindow
__all__ = ["AircontrolWindow", "MainWindow"]
