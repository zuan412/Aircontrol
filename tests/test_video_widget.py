"""Tests for the Aircontrol VideoWidget (Hardware OpenGL presentation)."""

import os
from unittest.mock import MagicMock
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from aircontrol.ui.video_widget import VideoWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_video_widget_initial_state(qapp):
    widget = VideoWidget()
    assert widget._image is None
    assert "iPhone" in widget._status_text

    widget.set_status_text("Đang tải luồng...")
    assert widget._status_text == "Đang tải luồng..."


def test_video_widget_post_frame_and_paint(qapp):
    widget = VideoWidget()
    widget.resize(400, 800)

    # 1. Post dummy 100x200 BGR0 frame (100 * 200 * 4 = 80000 bytes)
    dummy_bytes = b"\x00\xFF\x00\x00" * (100 * 200)
    widget.post_frame(dummy_bytes, 100, 200)

    assert widget._new_frame_available
    assert widget._current_width == 100
    assert widget._current_height == 200

    # 2. Paint pass
    widget.paintGL()
    assert not widget._new_frame_available
    assert widget._image is not None
    assert widget._image.width() == 100
    assert widget._image.height() == 200


def test_video_widget_post_frame_yuv_and_paint(qapp):
    widget = VideoWidget()
    widget.resize(400, 800)

    w, h = 100, 200
    y = b"\x80" * (w * h)
    u = b"\x80" * ((w // 2) * (h // 2))
    v = b"\x80" * ((w // 2) * (h // 2))

    widget.post_frame_yuv(y, u, v, w, h, w, w // 2, w // 2)

    assert widget._new_yuv_available
    assert widget._has_yuv_frame
    assert widget._current_width == 100
    assert widget._current_height == 200

    # Paint pass under offscreen test mode
    widget.paintGL()
    assert not widget._new_yuv_available
    assert widget._has_video_frame


def test_video_widget_fps_telemetry(qapp):
    widget = VideoWidget()
    fps_updates = []
    widget.on_fps_update = lambda fps, w, h: fps_updates.append((fps, w, h))

    # Post first frame
    w, h = 100, 200
    dummy_bytes = b"\x00\xFF\x00\x00" * (w * h)
    widget.post_frame(dummy_bytes, w, h)
    widget.paintGL()

    # Verify first frame triggers immediate telemetry update
    assert len(fps_updates) >= 1
    fps, rw, rh = fps_updates[0]
    assert rw == 100
    assert rh == 200



def test_video_widget_coordinate_mapping(qapp):
    widget = VideoWidget()
    widget.video_rect = QRect(10, 20, 100, 200)

    # Top-left inside rect
    coords = widget._map_to_norm_coords(QPoint(10, 20))
    assert coords == (0, 0)

    # Center inside rect
    coords_mid = widget._map_to_norm_coords(QPoint(60, 120))
    assert coords_mid is not None
    assert 30000 <= coords_mid[0] <= 35000
    assert 30000 <= coords_mid[1] <= 35000

    # Outside rect with clamp=False
    coords_out = widget._map_to_norm_coords(QPoint(0, 0), clamp=False)
    assert coords_out is None

    # Outside rect with clamp=True
    coords_clamped = widget._map_to_norm_coords(QPoint(0, 0), clamp=True)
    assert coords_clamped == (0, 0)


def test_video_widget_input_events(qapp):
    widget = VideoWidget()
    widget.video_rect = QRect(0, 0, 100, 200)

    touch_mock = MagicMock()
    scroll_mock = MagicMock()
    widget.on_touch = touch_mock
    widget.on_scroll = scroll_mock

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    press_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(50, 100),
        QPointF(50, 100),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press_event)
    assert touch_mock.called
    touch_mock.assert_called_with("contact", 32767, 32767)

    # Simulate mouse release
    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(50, 100),
        QPointF(50, 100),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(release_event)
    touch_mock.assert_called_with("release", 32767, 32767)


def test_video_widget_right_click_and_bottom_edge(qapp):
    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    home_mock = MagicMock()
    widget.on_home = home_mock

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    # 1. Right-click anywhere triggers on_home
    right_click = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(100, 200),
        QPointF(100, 200),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(right_click)
    assert home_mock.called

    # 2. Bottom bezel / edge coordinate snapping to 65535
    # Touch at bottom edge of video rect
    edge_coords = widget._map_to_norm_coords(QPoint(200, 755), clamp=False)
    assert edge_coords is not None
    assert edge_coords[1] == 65535

    # Touch inside bottom bezel (within 24px below video_rect.bottom())
    bezel_coords = widget._map_to_norm_coords(QPoint(200, 770), clamp=False)
    assert bezel_coords is not None
    assert bezel_coords[1] == 65535


def test_video_widget_home_zone_detection(qapp):
    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)  # bottom is at y=760

    # Center bottom (home bar area)
    assert widget._is_in_home_zone(QPoint(200, 750))
    assert widget._is_in_home_zone(QPoint(200, 765))

    # Top or middle of screen: NOT in home zone
    assert not widget._is_in_home_zone(QPoint(200, 100))
    assert not widget._is_in_home_zone(QPoint(200, 400))

    # Left or right screen edges: NOT in home bar width
    assert not widget._is_in_home_zone(QPoint(30, 750))
    assert not widget._is_in_home_zone(QPoint(370, 750))


def test_video_widget_home_bar_tap_to_home(qapp):
    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    home_mock = MagicMock()
    touch_mock = MagicMock()
    widget.on_home = home_mock
    widget.on_touch = touch_mock

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    # Mouse down on Home Bar (x=200, y=750)
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(200, 750),
        QPointF(200, 750),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press)
    assert widget._is_home_interaction
    # Home interaction isolates touch until gesture intent is resolved
    assert not touch_mock.called

    # Mouse release at same point (tap) -> triggers on_home
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(200, 750),
        QPointF(200, 750),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(release)
    assert home_mock.called
    assert not widget._is_home_interaction


def test_video_widget_home_bar_flick_to_home(qapp):
    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    touch_mock = MagicMock()
    home_mock = MagicMock()
    widget.on_touch = touch_mock
    widget.on_home = home_mock

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(200, 750),
        QPointF(200, 750),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press)

    # Mouse move upward by 80px (fast flick, elapsed < 0.35s)
    widget._last_touch_move_time = 0.0
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(200, 670),
        QPointF(200, 670),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseMoveEvent(move)

    # Release after fast flick -> triggers on_home
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(200, 670),
        QPointF(200, 670),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(release)
    assert home_mock.called


def test_video_widget_home_bar_drag_and_hold_app_switcher(qapp):
    """Verify that dragging up and holding triggers App Switcher."""
    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    touch_mock = MagicMock()
    home_mock = MagicMock()
    switcher_mock = MagicMock()
    widget.on_touch = touch_mock
    widget.on_home = home_mock
    widget.on_app_switcher = switcher_mock

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    # Start at Home bar
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(200, 750),
        QPointF(200, 750),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(press)

    # Drag to middle of screen (delta_y = 150px) and hold for 0.5 second
    widget._home_drag_start_time -= 0.50

    # Release while holding in the middle
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(200, 600),
        QPointF(200, 600),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(release)

    # Dwell in middle must trigger App Switcher!
    assert switcher_mock.called
    assert not home_mock.called


def test_video_widget_home_bar_double_click_app_switcher(qapp):
    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    switcher_mock = MagicMock()
    widget.on_app_switcher = switcher_mock

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    dbl_click = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick,
        QPointF(200, 750),
        QPointF(200, 750),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseDoubleClickEvent(dbl_click)
    assert switcher_mock.called


def test_video_widget_cleanup_gl(qapp):
    widget = VideoWidget()
    # cleanupGL should be robust and safe even without active context
    widget.cleanupGL()


def test_video_widget_landscape_rotation(qapp):
    widget = VideoWidget()
    widget._frame_width = 1296
    widget._frame_height = 2816
    widget.resize(800, 400)
    widget.video_rect = QRect(0, 0, 800, 400)

    # Portrait aspect (active iPhone display cropped from 1296x2816 encoder stream)
    assert widget.get_aspect_ratio() == pytest.approx(1284 / 2778)

    # Set landscape (270 degrees)
    widget._rotation_angle = 270
    assert widget.get_aspect_ratio() == pytest.approx(2778 / 1284)

    # Test coordinate mapping:
    # Clicking (0, 0) in landscape maps to (65535, 0) on portrait phone
    coords = widget._map_to_norm_coords(QPoint(0, 0))
    assert coords is not None
    assert coords[0] == 65535
    assert coords[1] == 0

    # Clicking bottom-right (800, 400) in landscape maps to (0, 65535) on portrait phone
    coords_br = widget._map_to_norm_coords(QPoint(800, 400), clamp=True)
    assert coords_br is not None
    assert coords_br[0] == 0
    assert coords_br[1] == 65535


def test_video_widget_borderless_full_bleed(qapp):
    widget = VideoWidget()
    widget.bezel_width = 0.0
    widget.resize(400, 869)

    dummy_bytes = b"\x00\xFF\x00\x00" * (100 * 200)
    widget.post_frame(dummy_bytes, 100, 200)
    widget.paintGL()

    # In pure borderless mode, video_rect MUST occupy 100% of widget surface (zero letterboxing, zero chin)
    assert widget.video_rect == QRect(0, 0, 400, 869)
    assert widget.video_rect.x() == 0
    assert widget.video_rect.y() == 0
    assert widget.video_rect.width() == 400
    assert widget.video_rect.height() == 869


def test_video_widget_keyboard_input_and_focus(qapp):
    from PySide6.QtGui import QKeyEvent, QFocusEvent
    from PySide6.QtCore import QEvent

    widget = VideoWidget()
    key_mock = MagicMock()
    focus_loss_mock = MagicMock()
    widget.on_key = key_mock
    widget.on_focus_loss = focus_loss_mock

    # 1. Key press A (HID code 4)
    event_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A.value, Qt.KeyboardModifier.NoModifier, "a")
    widget.keyPressEvent(event_press)
    key_mock.assert_called_with(4, True)

    # 2. Key release A (HID code 4)
    event_release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_A.value, Qt.KeyboardModifier.NoModifier, "a")
    widget.keyReleaseEvent(event_release)
    key_mock.assert_called_with(4, False)

    # 3. Focus loss triggers focus_loss_mock (releasing all keys)
    event_focus_out = QFocusEvent(QEvent.Type.FocusOut)
    widget.focusOutEvent(event_focus_out)
    assert focus_loss_mock.called

    # 4. Ctrl+V triggers on_paste
    paste_mock = MagicMock()
    widget.on_paste = paste_mock
    event_paste = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V.value, Qt.KeyboardModifier.ControlModifier, "v")
    widget.keyPressEvent(event_paste)
    assert paste_mock.called

    # 5. Escape triggers on_home
    home_mock = MagicMock()
    widget.on_home = home_mock
    event_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape.value, Qt.KeyboardModifier.NoModifier, "")
    widget.keyPressEvent(event_esc)
    assert home_mock.called


def test_video_widget_ios18_landscape_buffer_auto_rotation(qapp):
    """Test that raw 2816x1296 buffer from iOS hardware encoder correctly renders upright in portrait."""
    widget = VideoWidget()
    widget._frame_width = 2816
    widget._frame_height = 1296
    widget.resize(416, 900)

    # In default Portrait mode, aspect ratio must be ~0.4622 (upright phone)
    assert widget.get_aspect_ratio() == pytest.approx(1284 / 2778)
    assert not widget.is_landscape

    # In Landscape mode, aspect ratio must flip to ~2.1635 (widescreen phone)
    widget.set_orientation(is_landscape=True)
    assert widget.is_landscape
    assert widget.get_aspect_ratio() == pytest.approx(2778 / 1284)

    # Switch back to Portrait
    widget.set_orientation(is_landscape=False)
    assert not widget.is_landscape
    assert widget.get_aspect_ratio() == pytest.approx(1284 / 2778)


def test_video_widget_wheel_scroll_and_zoom(qapp):
    from PySide6.QtCore import QPointF, QPoint
    from PySide6.QtGui import QWheelEvent, QNativeGestureEvent

    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    scroll_calls = []
    zoom_calls = []
    widget.on_scroll = lambda up, x, y, is_h=False: scroll_calls.append((up, x, y, is_h))
    widget.on_zoom = lambda zoom_in, x, y: zoom_calls.append((zoom_in, x, y))

    # 1. Normal vertical scroll down (away from user = delta > 0 -> up=True)
    wheel_up = QWheelEvent(
        QPointF(200, 400),
        QPointF(200, 400),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(wheel_up)
    assert len(scroll_calls) == 1
    assert scroll_calls[-1][0] is True  # scroll_up = True
    assert scroll_calls[-1][3] is False  # is_horizontal = False

    # 2. Normal vertical scroll down (toward user = delta < 0 -> up=False)
    wheel_down = QWheelEvent(
        QPointF(200, 400),
        QPointF(200, 400),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(wheel_down)
    assert len(scroll_calls) == 2
    assert scroll_calls[-1][0] is False  # scroll_up = False
    assert scroll_calls[-1][3] is False

    # 3. Horizontal scroll (trackpad / horizontal wheel tilt)
    wheel_horiz = QWheelEvent(
        QPointF(200, 400),
        QPointF(200, 400),
        QPoint(0, 0),
        QPoint(120, 0),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(wheel_horiz)
    assert len(scroll_calls) == 3
    assert scroll_calls[-1][0] is True  # scroll_left = True
    assert scroll_calls[-1][3] is True  # is_horizontal = True

    # 4. Ctrl + Wheel Zoom In
    wheel_zoom_in = QWheelEvent(
        QPointF(200, 400),
        QPointF(200, 400),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(wheel_zoom_in)
    assert len(zoom_calls) == 1
    assert zoom_calls[-1][0] is True  # zoom_in = True

    # 5. Ctrl + Wheel Zoom Out
    wheel_zoom_out = QWheelEvent(
        QPointF(200, 400),
        QPointF(200, 400),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(wheel_zoom_out)
    assert len(zoom_calls) == 2
    assert zoom_calls[-1][0] is False  # zoom_in = False


def test_video_widget_double_click_forwards_to_touch(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    touch_mock = MagicMock()
    widget.on_touch = touch_mock

    # Double click inside screen content (center of screen: x=200, y=400)
    dbl_click = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick,
        QPointF(200, 400),
        QPointF(200, 400),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseDoubleClickEvent(dbl_click)

    # Must forward 2nd tap to touch as "contact"
    assert touch_mock.called
    touch_mock.assert_called_with("contact", pytest.approx(32768, abs=500), pytest.approx(32768, abs=500))


def test_video_widget_alt_pinch_gesture(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    widget = VideoWidget()
    widget.resize(400, 800)
    widget.video_rect = QRect(20, 40, 360, 720)

    multi_calls = []
    widget.on_multi_touch = lambda contacts: multi_calls.append(contacts)

    # 1. Press with Alt held down
    press_alt = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(250, 450),
        QPointF(250, 450),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
    )
    widget.mousePressEvent(press_alt)
    assert widget._is_alt_pinch is True
    assert len(multi_calls) == 1
    assert len(multi_calls[0]) == 2
    assert multi_calls[0][0][3] == "contact"
    assert multi_calls[0][1][3] == "contact"

    # 2. Move with Alt held down
    move_alt = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(280, 480),
        QPointF(280, 480),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
    )
    widget.mouseMoveEvent(move_alt)
    assert len(multi_calls) == 2
    assert multi_calls[1][0][3] == "move"
    assert multi_calls[1][1][3] == "move"

    # 3. Release
    release_alt = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(280, 480),
        QPointF(280, 480),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
    )
    widget.mouseReleaseEvent(release_alt)
    assert widget._is_alt_pinch is False
    assert len(multi_calls) == 3
    assert multi_calls[2][0][3] == "release"
    assert multi_calls[2][1][3] == "release"






