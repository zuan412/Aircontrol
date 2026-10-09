"""macOS Xcode Simulator style custom title bar for Aircontrol."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aircontrol.ui.icons import get_monochrome_icon


class TrafficLightButton(QPushButton):
    """macOS authentic red, yellow, green window control dot with subpixel accuracy."""

    def __init__(self, role: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.role = role  # 'close', 'minimize', 'maximize'
        self.setFixedSize(12, 12)
        self.setCursor(Qt.PointingHandCursor)
        self._show_glyph = False

    def set_glyph_visible(self, visible: bool) -> None:
        if self._show_glyph != visible:
            self._show_glyph = visible
            self.update()

    def enterEvent(self, event) -> None:
        p = self.parentWidget()
        if isinstance(p, TrafficLightGroup):
            p.set_group_hover(True)
        else:
            self.set_glyph_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        p = self.parentWidget()
        if isinstance(p, TrafficLightGroup):
            pos = p.mapFromGlobal(self.cursor().pos())
            if not p.rect().contains(pos):
                p.set_group_hover(False)
        else:
            self.set_glyph_visible(False)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Exact mathematical subpixel center
        cx = 6.0
        cy = 6.0
        radius = 5.5

        # macOS Sequoia traffic light colors & active states
        if self.role == "close":
            base_color = QColor(255, 95, 87) if not self.isDown() else QColor(191, 73, 66)
            border_color = QColor(224, 68, 62) if not self.isDown() else QColor(158, 51, 45)
            glyph_color = QColor(77, 0, 0, 204)
        elif self.role == "minimize":
            base_color = QColor(254, 188, 46) if not self.isDown() else QColor(191, 142, 34)
            border_color = QColor(222, 161, 35) if not self.isDown() else QColor(158, 110, 20)
            glyph_color = QColor(153, 87, 0, 217)
        else:  # maximize / fullscreen
            base_color = QColor(40, 200, 64) if not self.isDown() else QColor(30, 150, 48)
            border_color = QColor(26, 171, 41) if not self.isDown() else QColor(19, 120, 30)
            glyph_color = QColor(0, 101, 0, 217)

        # Draw smooth circle dot
        circle_rect = QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)
        painter.setBrush(base_color)
        painter.setPen(QPen(border_color, 0.75))
        painter.drawEllipse(circle_rect)

        # Draw authentic macOS glyphs when hovered (subpixel centered)
        if self._show_glyph:
            if self.role == "close":
                # Perfectly centered hairline diagonal cross
                d = 2.4
                pen = QPen(glyph_color, 1.15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(QLineF(cx - d, cy - d, cx + d, cy + d))
                painter.drawLine(QLineF(cx - d, cy + d, cx + d, cy - d))
            elif self.role == "minimize":
                # Perfectly centered horizontal bar
                d = 2.8
                pen = QPen(glyph_color, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(QLineF(cx - d, cy, cx + d, cy))
            else:
                # macOS Fullscreen: two opposing filled diagonal triangles
                painter.setBrush(glyph_color)
                painter.setPen(Qt.PenStyle.NoPen)

                p_top = QPainterPath()
                p_top.moveTo(cx - 0.2, cy - 3.2)
                p_top.lineTo(cx + 3.2, cy - 3.2)
                p_top.lineTo(cx + 3.2, cy + 0.2)
                p_top.closeSubpath()
                painter.drawPath(p_top)

                p_bot = QPainterPath()
                p_bot.moveTo(cx + 0.2, cy + 3.2)
                p_bot.lineTo(cx - 3.2, cy + 3.2)
                p_bot.lineTo(cx - 3.2, cy - 0.2)
                p_bot.closeSubpath()
                painter.drawPath(p_bot)

        painter.end()


class TrafficLightGroup(QWidget):
    """Container for the 3 macOS traffic light buttons providing authentic group hover."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(12)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_close = TrafficLightButton("close", self)
        self.btn_min = TrafficLightButton("minimize", self)
        self.btn_max = TrafficLightButton("maximize", self)

        layout.addWidget(self.btn_close)
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)

    def set_group_hover(self, hovered: bool) -> None:
        self.btn_close.set_glyph_visible(hovered)
        self.btn_min.set_glyph_visible(hovered)
        self.btn_max.set_glyph_visible(hovered)

    def enterEvent(self, event) -> None:
        self.set_group_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.set_group_hover(False)
        super().leaveEvent(event)


class ActionIconButton(QPushButton):
    """Minimalist rounded action button with crisp vector icon."""

    def __init__(self, icon_type: str, tooltip: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.icon_type = icon_type
        self.setToolTip(tooltip)
        self.is_active: bool = False
        self.setFixedSize(28, 24)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        # Seamless button background: completely borderless in normal resting state
        if self.is_active:
            bg = QColor(10, 132, 255, 38)
            border = QColor(10, 132, 255, 85)
            icon_color = QColor(41, 151, 255)  # Apple vibrant blue
        elif self.isDown():
            bg = QColor(255, 255, 255, 30)
            border = QColor(255, 255, 255, 45)
            icon_color = QColor(255, 255, 255)
        elif self.underMouse():
            bg = QColor(255, 255, 255, 20)
            border = QColor(255, 255, 255, 28)
            icon_color = QColor(255, 255, 255)
        else:
            bg = Qt.BrushStyle.NoBrush
            border = Qt.PenStyle.NoPen
            icon_color = QColor(161, 167, 181)  # Sleek muted silver-slate

        if bg != Qt.BrushStyle.NoBrush:
            painter.setBrush(bg)
            painter.setPen(border)
            painter.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)

        # Vector Icon with dynamic state-aware color
        painter.setPen(QPen(icon_color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = float(r.width() / 2), float(r.height() / 2)

        if self.icon_type == "home":
            # House silhouette
            path = QPainterPath()
            path.moveTo(cx - 5.5, cy + 4.5)
            path.lineTo(cx - 5.5, cy - 0.5)
            path.lineTo(cx, cy - 5.5)
            path.lineTo(cx + 5.5, cy - 0.5)
            path.lineTo(cx + 5.5, cy + 4.5)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(QPointF(cx - 1.8, cy + 4.5), QPointF(cx - 1.8, cy + 1.2))
            painter.drawLine(QPointF(cx + 1.8, cy + 4.5), QPointF(cx + 1.8, cy + 1.2))

        elif self.icon_type == "camera":
            # Camera silhouette
            path = QPainterPath()
            path.addRoundedRect(QRectF(cx - 6.5, cy - 3.5, 13.0, 9.0), 2.0, 2.0)
            path.moveTo(cx - 2.5, cy - 3.5)
            path.lineTo(cx - 1.5, cy - 5.5)
            path.lineTo(cx + 1.5, cy - 5.5)
            path.lineTo(cx + 2.5, cy - 3.5)
            painter.drawPath(path)
            painter.drawEllipse(QPointF(cx, cy + 1.0), 2.2, 2.2)

        elif self.icon_type == "rotate":
            # Curved rotation arrow
            painter.drawArc(QRectF(cx - 5.5, cy - 5.5, 11.0, 11.0), 45 * 16, 270 * 16)
            arrow = QPainterPath()
            arrow.moveTo(cx + 3.5, cy - 5.5)
            arrow.lineTo(cx + 6.5, cy - 3.5)
            arrow.lineTo(cx + 3.5, cy - 1.5)
            painter.drawPath(arrow)

        elif self.icon_type == "lock":
            # Padlock
            path = QPainterPath()
            path.addRoundedRect(QRectF(cx - 5.0, cy - 1.5, 10.0, 7.5), 1.5, 1.5)
            painter.drawPath(path)
            # Shackle
            shackle = QPainterPath()
            shackle.arcMoveTo(QRectF(cx - 3.5, cy - 6.0, 7.0, 7.0), 0)
            shackle.arcTo(QRectF(cx - 3.5, cy - 6.0, 7.0, 7.0), 0, 180)
            painter.drawPath(shackle)

        elif self.icon_type == "unlock":
            # Swipe-up double chevron
            p1 = QPainterPath()
            p1.moveTo(cx - 4.5, cy + 2.0)
            p1.lineTo(cx, cy - 2.0)
            p1.lineTo(cx + 4.5, cy + 2.0)
            painter.drawPath(p1)
            p2 = QPainterPath()
            p2.moveTo(cx - 4.5, cy - 1.5)
            p2.lineTo(cx, cy - 5.5)
            p2.lineTo(cx + 4.5, cy - 1.5)
        elif self.icon_type == "borderless":
            # Overlapping frames (toggle between hardware chassis and borderless)
            path1 = QPainterPath()
            path1.addRoundedRect(QRectF(cx - 5.5, cy - 5.0, 8.5, 8.5), 1.5, 1.5)
            painter.drawPath(path1)
            path2 = QPainterPath()
            path2.addRoundedRect(QRectF(cx - 3.0, cy - 2.5, 8.5, 8.5), 1.5, 1.5)
            painter.drawPath(path2)

        elif self.icon_type == "keyboard":
            # Apple Magic Keyboard chassis silhouette
            path = QPainterPath()
            path.addRoundedRect(QRectF(cx - 6.5, cy - 4.5, 13.0, 9.0), 2.0, 2.0)
            painter.drawPath(path)
            # Keys grid (minimalist micro-strokes)
            painter.drawLine(QPointF(cx - 4.0, cy - 1.8), QPointF(cx - 2.5, cy - 1.8))
            painter.drawLine(QPointF(cx - 0.7, cy - 1.8), QPointF(cx + 0.7, cy - 1.8))
            painter.drawLine(QPointF(cx + 2.5, cy - 1.8), QPointF(cx + 4.0, cy - 1.8))
            # Spacebar line
            painter.drawLine(QPointF(cx - 3.2, cy + 1.8), QPointF(cx + 3.2, cy + 1.8))

        elif self.icon_type in ("speaker", "speaker_muted"):
            # Speaker body & cone
            spk = QPainterPath()
            spk.moveTo(cx - 5.5, cy - 2.5)
            spk.lineTo(cx - 2.5, cy - 2.5)
            spk.lineTo(cx + 1.0, cy - 5.5)
            spk.lineTo(cx + 1.0, cy + 5.5)
            spk.lineTo(cx - 2.5, cy + 2.5)
            spk.lineTo(cx - 5.5, cy + 2.5)
            spk.closeSubpath()
            painter.drawPath(spk)

            if self.icon_type == "speaker":
                # Sound wave arcs
                painter.drawArc(QRectF(cx - 2.0, cy - 3.5, 7.0, 7.0), -40 * 16, 80 * 16)
                painter.drawArc(QRectF(cx - 3.5, cy - 5.5, 11.0, 11.0), -40 * 16, 80 * 16)
            else:
                # Diagonal mute slash
                painter.setPen(QPen(QColor(235, 80, 80), 1.5, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(QPointF(cx - 5.0, cy + 5.0), QPointF(cx + 5.0, cy - 5.0))

        elif self.icon_type == "moon":
            # Minimalist crescent moon
            m_path = QPainterPath()
            m_path.arcMoveTo(QRectF(cx - 5.0, cy - 5.0, 10.0, 10.0), 30)
            m_path.arcTo(QRectF(cx - 5.0, cy - 5.0, 10.0, 10.0), 30, 260)
            m_path.arcTo(QRectF(cx - 1.5, cy - 4.0, 7.0, 8.0), 200, -180)
            m_path.closeSubpath()
            painter.drawPath(m_path)

        elif self.icon_type == "more":
            # Three horizontal dots (More Options)
            painter.setBrush(icon_color)
            painter.setPen(Qt.PenStyle.NoPen)
            dot_r = 1.5
            painter.drawEllipse(QPointF(cx - 5.0, cy), dot_r, dot_r)
            painter.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
            painter.drawEllipse(QPointF(cx + 5.0, cy), dot_r, dot_r)

        painter.end()


class SimulatorTitleBar(QWidget):
    """Sleek macOS Simulator header with traffic lights, centered title, and action icons."""

    close_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()

    home_requested = Signal()
    app_switcher_requested = Signal()
    screenshot_requested = Signal()
    rotate_requested = Signal()
    lock_requested = Signal()
    unlock_requested = Signal()
    borderless_requested = Signal()
    keyboard_toggle_requested = Signal()
    audio_toggle_requested = Signal()
    dim_screen_requested = Signal()
    skin_selected = Signal(str)
    always_on_top_requested = Signal()
    open_screenshots_requested = Signal()
    paste_clipboard_requested = Signal()

    def __init__(self, device_name: str = "iPhone", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.device_name = device_name
        self.device_subtitle = "Chờ kết nối (USB / Wi-Fi)..."

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._drag_pos: Optional[QPointF] = None
        self.setFixedHeight(34)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("SimulatorTitleBar")
        self.setStyleSheet("""
            QWidget#SimulatorTitleBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1C1F28, stop:1 #14161E);
                border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        # 1. Left: macOS Traffic Lights (authentic spacing & group hover)
        self.traffic_lights = TrafficLightGroup(self)
        self.btn_close = self.traffic_lights.btn_close
        self.btn_min = self.traffic_lights.btn_min
        self.btn_max = self.traffic_lights.btn_max

        self.btn_close.clicked.connect(self.close_requested.emit)
        self.btn_min.clicked.connect(self.minimize_requested.emit)
        self.btn_max.clicked.connect(self.maximize_requested.emit)

        layout.addWidget(self.traffic_lights, stretch=0)

        # 2. Center: Centered Device Name + Telemetry Capsule Badge
        layout.addStretch(1)
        center_widget = QWidget(self)
        center_widget.setStyleSheet("background: transparent;")
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 1, 0, 1)
        center_layout.setSpacing(1)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_title = QLabel(self.device_name, center_widget)
        title_font = QFont()
        title_font.setFamilies(["Be Vietnam Pro", "Segoe UI Variable Text", "Segoe UI", "Arial"])
        title_font.setPointSize(9)
        title_font.setBold(True)
        self.lbl_title.setFont(title_font)
        self.lbl_title.setStyleSheet("color: #FFFFFF; background: transparent;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.lbl_title)

        self.lbl_sub = QLabel(self.device_subtitle, center_widget)
        self.lbl_sub.setObjectName("TelemetryBadge")
        sub_font = QFont()
        sub_font.setFamilies(["Be Vietnam Pro", "Segoe UI Variable Text", "Segoe UI", "Arial"])
        sub_font.setPointSizeF(8.5)
        self.lbl_sub.setFont(sub_font)
        self.lbl_sub.setStyleSheet("""
            QLabel#TelemetryBadge {
                color: #9CA3AF;
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 1px 6px;
            }
        """)
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.lbl_sub)

        layout.addWidget(center_widget, stretch=0)
        layout.addStretch(1)

        # 3. Right: Essential 3-Action Cluster ([Audio] [Camera] [More])
        right_layout = QHBoxLayout()
        right_layout.setSpacing(4)

        # Primary 3 visible action buttons
        self.btn_audio = ActionIconButton("speaker", "Âm thanh iPhone (Phát qua loa máy tính: Bật)", self)
        self.btn_audio.is_active = True
        self.btn_audio.clicked.connect(self.audio_toggle_requested.emit)
        right_layout.addWidget(self.btn_audio)

        self.btn_camera = ActionIconButton("camera", "Chụp ảnh màn hình (Ctrl+P)", self)
        self.btn_camera.clicked.connect(self.screenshot_requested.emit)
        right_layout.addWidget(self.btn_camera)

        self.btn_more = ActionIconButton("more", "Tùy chọn khác (•••)", self)
        self.btn_more.clicked.connect(self._show_more_menu)
        right_layout.addWidget(self.btn_more)

        # Secondary action buttons (accessible via menu / global hotkeys)
        self.btn_home = ActionIconButton("home", "Về màn hình chính (Ctrl+H)", self)
        self.btn_home.clicked.connect(self.home_requested.emit)
        self.btn_home.hide()

        self.btn_unlock = ActionIconButton("unlock", "Vuốt mở khóa (Ctrl+U)", self)
        self.btn_unlock.clicked.connect(self.unlock_requested.emit)
        self.btn_unlock.hide()

        self.btn_keyboard = ActionIconButton("keyboard", "Bàn phím ảo iPhone (Nhấn để gõ / ESC để thoát)", self)
        self.btn_keyboard.clicked.connect(self.keyboard_toggle_requested.emit)
        self.btn_keyboard.hide()

        self.btn_borderless = ActionIconButton("borderless", "Bật / Tắt Khung viền iPhone (Ctrl+B)", self)
        self.btn_borderless.clicked.connect(self.borderless_requested.emit)
        self.btn_borderless.hide()

        self.btn_rotate = ActionIconButton("rotate", "Xoay màn hình (Ctrl+R)", self)
        self.btn_rotate.clicked.connect(self.rotate_requested.emit)
        self.btn_rotate.hide()

        self.btn_dim = ActionIconButton("moon", "Tắt / Giảm tối màn hình iPhone (Ctrl+Shift+D)", self)
        self.btn_dim.clicked.connect(self.dim_screen_requested.emit)
        self.btn_dim.hide()

        self.btn_lock = ActionIconButton("lock", "Khóa / Mở màn hình (Ctrl+L)", self)
        self.btn_lock.clicked.connect(self.lock_requested.emit)
        self.btn_lock.hide()

        layout.addLayout(right_layout, stretch=0)

        self._skins_list: list[str] = []
        self._current_skin_id: str = "iphone-16-pro-natural"

    def setup_skins_menu(self, skins: list[str] | dict[str, Any], current_skin_id: str) -> None:
        """Store available skins and active skin for dropdown selection."""
        if isinstance(skins, dict):
            self._skins_list = list(skins.keys())
        else:
            self._skins_list = list(skins)
        self._current_skin_id = current_skin_id

    def trigger_skin_selection(self, skin_id: str) -> None:
        """Helper to invoke skin selection programmatically or from menu."""
        self._current_skin_id = skin_id
        self.skin_selected.emit(skin_id)

    def _show_more_menu(self) -> None:
        """Open modern Apple-style popover HUD menu with monochrome icons and right-aligned shortcuts."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #16181F;
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 10px;
                padding: 5px;
                color: #F3F4F6;
                font-family: 'Be Vietnam Pro', 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QMenu::item {
                padding: 7px 22px 7px 10px;
                border-radius: 6px;
                margin: 1px 0px;
            }
            QMenu::icon {
                padding-left: 4px;
                padding-right: 8px;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
            }
            QMenu::shortcut {
                color: #6B7280;
                font-size: 11px;
                font-weight: 500;
                padding-left: 20px;
            }
            QMenu::separator {
                height: 1px;
                background-color: rgba(255, 255, 255, 0.07);
                margin: 4px 6px;
            }
            QMenu::right-arrow {
                image: none;
                width: 0;
                height: 0;
                border-left: 4px solid #6B7280;
                border-top: 3px solid transparent;
                border-bottom: 3px solid transparent;
                margin-right: 6px;
            }
            QMenu::right-arrow:selected {
                border-left: 4px solid #FFFFFF;
            }
        """)

        act_home = menu.addAction(get_monochrome_icon("home"), "Màn hình chính")
        act_home.setShortcut(QKeySequence("Ctrl+H"))
        act_home.triggered.connect(self.home_requested.emit)

        act_switcher = menu.addAction(get_monochrome_icon("app_switcher"), "Bộ chuyển đổi ứng dụng")
        act_switcher.setShortcut(QKeySequence("Ctrl+Tab"))
        act_switcher.triggered.connect(self.app_switcher_requested.emit)

        menu.addSeparator()

        act_borderless = menu.addAction(get_monochrome_icon("frame"), "Bật / Tắt viền cửa sổ")
        act_borderless.setShortcut(QKeySequence("Ctrl+B"))
        act_borderless.triggered.connect(self.borderless_requested.emit)

        if hasattr(self, "_skins_list") and self._skins_list:
            skins_menu = menu.addMenu(get_monochrome_icon("frame"), "Vỏ máy mô phỏng")
            for s_id in self._skins_list:
                s_name = s_id.replace("-", " ").title()
                if s_id == "stage-manager-clean":
                    s_name = "Không viền (Bo góc nhẹ)"
                elif s_id == "iphone-16-pro-natural":
                    s_name = "iPhone 16 Pro (Titan Tự nhiên)"
                elif s_id == "iphone-16-pro-black":
                    s_name = "iPhone 16 Pro (Titan Đen)"
                elif s_id == "iphone-15":
                    s_name = "iPhone 15 (Nhôm chuẩn)"

                act_s = skins_menu.addAction(s_name)
                act_s.setCheckable(True)
                act_s.setChecked(s_id == getattr(self, "_current_skin_id", ""))
                act_s.triggered.connect(lambda checked=False, target_id=s_id: self.skin_selected.emit(target_id))

        act_rotate = menu.addAction(get_monochrome_icon("rotate"), "Xoay màn hình")
        act_rotate.setShortcut(QKeySequence("Ctrl+R"))
        act_rotate.triggered.connect(self.rotate_requested.emit)

        act_keyboard = menu.addAction(get_monochrome_icon("keyboard"), "Bàn phím ảo")
        act_keyboard.setShortcut(QKeySequence("Ctrl+K"))
        act_keyboard.triggered.connect(self.keyboard_toggle_requested.emit)

        act_paste = menu.addAction(get_monochrome_icon("clipboard"), "Dán từ Clipboard PC")
        act_paste.setShortcut(QKeySequence("Ctrl+Shift+V"))
        act_paste.triggered.connect(self.paste_clipboard_requested.emit)

        win = self.window()
        is_pinned = getattr(win, "is_always_on_top", False)
        pin_label = "Bỏ ghim cửa sổ" if is_pinned else "Ghim trên cùng"
        act_pin = menu.addAction(get_monochrome_icon("pin"), pin_label)
        act_pin.setCheckable(True)
        act_pin.setChecked(is_pinned)
        act_pin.setShortcut(QKeySequence("Ctrl+T"))
        act_pin.triggered.connect(self.always_on_top_requested.emit)

        act_folder = menu.addAction(get_monochrome_icon("folder"), "Mở thư mục ảnh chụp...")
        act_folder.triggered.connect(self.open_screenshots_requested.emit)

        menu.addSeparator()

        act_dim = menu.addAction(get_monochrome_icon("moon"), "Giảm sáng màn hình iPhone")
        act_dim.setShortcut(QKeySequence("Ctrl+Shift+D"))
        act_dim.triggered.connect(self.dim_screen_requested.emit)

        act_lock = menu.addAction(get_monochrome_icon("lock"), "Khóa / Mở màn hình")
        act_lock.setShortcut(QKeySequence("Ctrl+L"))
        act_lock.triggered.connect(self.lock_requested.emit)

        # Smart positioning: Open to the RIGHT of the window to keep the phone display 100% unobstructed
        win = self.window()
        screen = win.screen() if win and win.screen() else (self.screen() or QApplication.primaryScreen())
        screen_geo = screen.availableGeometry() if screen else None

        menu_size = menu.sizeHint()
        menu_w = menu_size.width()
        menu_h = menu_size.height()

        if win:
            win_geo = win.geometry()
            # Float neatly to the right side of the iPhone window
            target_x = win_geo.right() + 6
            target_y = win_geo.top() + 4

            # If not enough room on the right, position to the left of the window
            if screen_geo and (target_x + menu_w > screen_geo.right()):
                target_x = win_geo.left() - menu_w - 6
                # If also constrained on left, clamp
                if target_x < screen_geo.left():
                    target_x = max(screen_geo.left(), win_geo.right() - menu_w)

            # Keep vertically within screen bounds
            if screen_geo and (target_y + menu_h > screen_geo.bottom()):
                target_y = max(screen_geo.top(), screen_geo.bottom() - menu_h - 10)

            pos = QPoint(target_x, target_y)
        else:
            pos = self.btn_more.mapToGlobal(QPoint(self.btn_more.width() + 6, 0))

        menu.exec(pos)

    def set_device_info(self, title: str, subtitle: Optional[str] = None) -> None:
        self.device_name = title
        self.lbl_title.setText(title)
        if subtitle is not None:
            self.device_subtitle = subtitle
            self.lbl_sub.setText(subtitle)
        self.setToolTip(f"{self.device_name} • {self.device_subtitle}")

    def set_telemetry(self, fps: int, width: int, height: int, connection: str = "Wi-Fi") -> None:
        self.lbl_sub.setText(f"{fps} FPS • {width}x{height}")
        self.setToolTip(f"{self.device_name} ({connection}) • {fps} FPS • {width}x{height}")

    def set_audio_state(self, muted: bool) -> None:
        if muted:
            self.btn_audio.icon_type = "speaker_muted"
            self.btn_audio.setToolTip("Âm thanh iPhone (Đang tắt tiếng - Nhấp để bật)")
            self.btn_audio.is_active = False
        else:
            self.btn_audio.icon_type = "speaker"
            self.btn_audio.setToolTip("Âm thanh iPhone (Đang phát qua loa máy tính)")
            self.btn_audio.is_active = True
        self.btn_audio.update()

    # --- Frameless Window Dragging ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            if win:
                self._drag_pos = event.globalPosition().toPoint() - win.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            win = self.window()
            if win and not win.isMaximized():
                win.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
        super().mouseDoubleClickEvent(event)
