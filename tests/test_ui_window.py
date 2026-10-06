import os
import pytest

# Ensure offscreen Qt rendering for headless CI / unit test
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from aircontrol.ui.simulator_titlebar import SimulatorTitleBar
from aircontrol.ui.window import AircontrolWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_titlebar_integration(qapp):
    win = AircontrolWindow()
    assert win.title_bar is not None
    assert win.title_bar.btn_close is not None
    assert win.title_bar.btn_rotate is not None
    assert win.title_bar.btn_audio is not None


def test_window_creation(qapp):
    win = AircontrolWindow()
    assert win is not None
    assert "Aircontrol" in win.windowTitle()
    assert win.toolbar is not None


def test_window_tight_geometry_and_centering(qapp):
    win = AircontrolWindow()
    win.show()
    qapp.processEvents()

    # Geometry must be proportioned to iPhone portrait (aspect ~ 9/19.5)
    w = win.width()
    h = win.height()
    assert 280 <= w <= 500
    assert 520 <= h <= 1200
    aspect_ratio = float(w) / float(h)
    assert 0.40 <= aspect_ratio <= 0.50, f"Window ratio {aspect_ratio} must hug iPhone proportions"

    # Calculation functions must match tight fitting
    calc_w = win._calc_window_width(h)
    assert abs(calc_w - w) <= 4


def test_window_zoom_toggle_and_anti_maximize(qapp):
    win = AircontrolWindow()
    win.show()
    qapp.processEvents()

    orig_h = win.height()
    win._toggle_zoom()
    qapp.processEvents()
    assert not win.isMaximized(), "Zoom toggle must never produce full-screen maximized window"

    # Test intercepting maximize state
    win.showMaximized()
    qapp.processEvents()
    assert not win.isMaximized(), "Window must intercept maximize and stay in normal frame"


def test_window_app_switcher_and_device_status(qapp):
    from unittest.mock import MagicMock
    win = AircontrolWindow()
    mock_hid = MagicMock()
    win.hid_controller = mock_hid

    # App switcher triggered
    win._handle_app_switcher()
    assert mock_hid.send_app_switcher_sync.called

    # Device status update
    win.update_device_status(connected=True, name="iPhone 15 Pro", model="iOS 18.0", conn_type="Wi-Fi")
    assert "iPhone 15 Pro" in win.windowTitle()
    assert "Wi-Fi" in win.title_bar.lbl_sub.text()

    win.update_device_status(connected=False)
    assert "Chờ kết nối" in win.windowTitle()


def test_window_rotation_toggle(qapp):
    win = AircontrolWindow()
    win.show()
    qapp.processEvents()

    # Initial state: Portrait (0 degrees)
    assert win.video_widget._rotation_angle == 0
    w_port = win.width()
    h_port = win.height()
    assert h_port > w_port

    # Trigger rotation -> Landscape (270 degrees)
    win._on_rotate()
    qapp.processEvents()

    assert win.video_widget._rotation_angle == 270
    w_land = win.width()
    h_land = win.height()
    assert w_land > h_land, "Landscape window must be wider than tall"
    assert win.title_bar.width() == win.width(), "Titlebar must stretch to match full landscape width"

    # Trigger rotation back -> Portrait (0 degrees)
    win._on_rotate()
    qapp.processEvents()

    assert win.video_widget._rotation_angle == 0
    assert win.height() > win.width(), "Portrait window must be taller than wide"


def test_window_borderless_toggle(qapp):
    win = AircontrolWindow()
    win.show()
    qapp.processEvents()

    assert not win.is_borderless
    assert win.video_widget.bezel_width == win.current_skin.bezel_width
    assert win.title_bar.isVisible()

    # Toggle to Borderless
    win.toggle_borderless()
    qapp.processEvents()

    assert win.is_borderless
    assert win.video_widget.bezel_width == 0.0
    assert win.title_bar.isHidden()

    # In pure borderless mode, aspect ratio must match screen directly
    aspect = win.video_widget.get_aspect_ratio()
    calc_w = win._calc_window_width(win.height(), aspect=aspect)
    assert abs(calc_w - win.width()) <= 1

    # Toggle back to Frame mode
    win.toggle_borderless()
    qapp.processEvents()

    assert not win.is_borderless
    assert win.video_widget.bezel_width == win.current_skin.bezel_width
    assert win.title_bar.isVisible()


def test_window_uniform_bezel_proportions(qapp):
    win = AircontrolWindow()
    win.show()
    qapp.processEvents()

    # In edge-to-edge mode, calculating width from height and back must be invertible
    aspect = 9.0 / 19.5
    h = 800
    w = win._calc_window_width(h, aspect=aspect)
    h_back = win._calc_window_height(w, aspect=aspect)
    assert abs(h - h_back) <= 2


def test_window_border_resizing_and_no_auto_rotate(qapp):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    win = AircontrolWindow()
    win.show()
    qapp.processEvents()

    # 1. Verify VideoWidget has NO intrusive handle overlay eating into the screen
    assert win.video_widget.resize_handle is None

    # 2. Test proportional snug-fit corner resize
    orig_h = win.height()
    orig_w = win.width()
    press_pos = QPointF(float(orig_w - 5), float(orig_h - 5))
    press_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        press_pos,
        press_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.mousePressEvent(press_event)
    assert win._resize_edge == "corner"

    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        press_pos + QPointF(30, 60),
        press_pos + QPointF(30, 60),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.mouseMoveEvent(move_event)
    assert win.height() == orig_h + 60
    assert win.width() == win._calc_window_width(win.height())

    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        press_pos + QPointF(30, 60),
        press_pos + QPointF(30, 60),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.mouseReleaseEvent(release_event)
    assert win._resize_edge is None

    # 3. Test that dragging far to the right does NOT auto-rotate to Landscape
    assert win.video_widget._rotation_angle == 0
    win.mousePressEvent(press_event)
    move_far_right = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        press_pos + QPointF(200, 20),
        press_pos + QPointF(200, 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.mouseMoveEvent(move_far_right)
    assert win.video_widget._rotation_angle == 0, "Resizing must never auto-rotate the screen to Landscape"
    assert win.height() > win.width(), "Screen must stay in Portrait mode"
    win.mouseReleaseEvent(release_event)

    # 4. In Landscape mode, test that dragging far downward does NOT auto-rotate to Portrait
    win.set_orientation(270)
    assert win.video_widget._rotation_angle == 270
    land_w = win.width()
    land_h = win.height()
    press_land = QPointF(float(land_w - 5), float(land_h - 5))
    win.mousePressEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            press_land,
            press_land,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    win.mouseMoveEvent(
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            press_land + QPointF(20, 200),
            press_land + QPointF(20, 200),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert win.video_widget._rotation_angle == 270, "Resizing must never auto-rotate the screen to Portrait"
    assert win.width() > win.height(), "Screen must stay in Landscape mode"
    win.mouseReleaseEvent(release_event)



def test_window_dim_screen_toggle(qapp):
    from unittest.mock import MagicMock
    win = AircontrolWindow()
    mock_hid = MagicMock()
    mock_hid._dimmed_screen_steps = 0
    win.hid_controller = mock_hid

    # 1. Dim screen
    win._toggle_dim_screen()
    assert mock_hid.dim_device_screen_sync.called
    assert win.title_bar.btn_dim.is_active is True

    # 2. Restore screen
    mock_hid._dimmed_screen_steps = 16
    win._toggle_dim_screen()
    assert mock_hid.restore_device_screen_sync.called
    assert win.title_bar.btn_dim.is_active is False


def test_window_sync_to_stream_aspect(qapp):
    win = AircontrolWindow()
    win.show()
    win.video_widget._frame_width = 2816
    win.video_widget._frame_height = 1296
    win.sync_to_stream_aspect()
    assert win.width() == win._calc_window_width(win.height())


def test_window_skin_switching(qapp):
    win = AircontrolWindow()
    assert hasattr(win, "skin_manager")
    assert win.current_skin.id == "stage-manager-clean"
    assert win.video_widget.bezel_width == 0.0

    # Switch to iPhone 16 Pro Black
    win.set_skin("iphone-16-pro-black")
    assert win.current_skin.id == "iphone-16-pro-black"
    assert win.video_widget.bezel_width > 0.0
    assert win.current_skin.chassis_color == (0.18, 0.19, 0.22)

    # Test titlebar signal connection
    win.title_bar.skin_selected.emit("iphone-15")
    assert win.current_skin.id == "iphone-15"


def test_window_home_and_switcher_shortcuts(qapp):
    from unittest.mock import MagicMock
    win = AircontrolWindow()
    mock_hid = MagicMock()
    win.hid_controller = mock_hid

    # Find Home action
    actions = win.actions()
    home_acts = [a for a in actions if any(s.toString() in ("Ctrl+1", "Ctrl+H", "Esc") for s in a.shortcuts())]
    assert len(home_acts) >= 1
    home_acts[0].trigger()
    assert mock_hid.send_home_sync.called

    # Find Switcher action
    switcher_acts = [a for a in actions if any(s.toString() in ("Ctrl+2", "Ctrl+Tab") for s in a.shortcuts())]
    assert len(switcher_acts) >= 1
    switcher_acts[0].trigger()
    assert mock_hid.send_app_switcher_sync.called


def test_window_scroll_and_zoom_handlers(qapp):
    from unittest.mock import MagicMock
    win = AircontrolWindow()
    mock_hid = MagicMock()
    win.hid_controller = mock_hid

    # 1. Vertical scroll
    win._handle_scroll(scroll_up=True, norm_x=30000, norm_y=40000, is_horizontal=False)
    mock_hid.send_scroll_swipe_sync.assert_called_with(30000, 40000, True, False)

    # 2. Horizontal scroll
    win._handle_scroll(scroll_up=False, norm_x=30000, norm_y=40000, is_horizontal=True)
    mock_hid.send_scroll_swipe_sync.assert_called_with(30000, 40000, False, True)

    # 3. Zoom gesture
    win._handle_zoom(zoom_in=True, norm_x=32000, norm_y=35000)
    mock_hid.send_zoom_sync.assert_called_with(32000, 35000, True)

    win._handle_zoom(zoom_in=False, norm_x=32000, norm_y=35000)
    mock_hid.send_zoom_sync.assert_called_with(32000, 35000, False)


def test_window_always_on_top_toggle(qapp):
    from PySide6.QtCore import Qt
    win = AircontrolWindow()
    assert not win.is_always_on_top
    assert not (win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    win.toggle_always_on_top()
    assert win.is_always_on_top
    assert bool(win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    win.toggle_always_on_top()
    assert not win.is_always_on_top
    assert not (win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def test_window_paste_clipboard_to_phone(qapp):
    from unittest.mock import MagicMock
    win = AircontrolWindow()
    mock_hid = MagicMock()
    win.hid_controller = mock_hid

    qapp.clipboard().setText("Aircontrol Test Message")
    win.paste_clipboard_to_phone()
    mock_hid.send_ascii_text_sync.assert_called_with("Aircontrol Test Message")


def test_window_screenshot_directory_and_clipboard(qapp):
    from pathlib import Path
    from PySide6.QtGui import QImage
    win = AircontrolWindow()

    # Provide a dummy image
    dummy_img = QImage(100, 200, QImage.Format.Format_RGB32)
    dummy_img.fill(0xFF00FF)
    win.video_widget._image = dummy_img

    try:
        win._on_screenshot()
        screenshots_dir = Path("screenshots").resolve()
        assert screenshots_dir.exists()
        assert screenshots_dir.is_dir()

        # Verify clipboard has image
        clip_img = qapp.clipboard().image()
        assert not clip_img.isNull()
    finally:
        for f in screenshots_dir.glob("iPhone_screenshot_*.png"):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass


def test_main_window_alias():
    from aircontrol.ui.window import AircontrolWindow, MainWindow
    assert MainWindow is AircontrolWindow


def test_window_paste_clipboard_with_pasteboard_mgr(qapp):
    from unittest.mock import MagicMock
    win = AircontrolWindow()
    mock_hid = MagicMock()
    mock_pbm = MagicMock()
    win.hid_controller = mock_hid
    win.pasteboard_mgr = mock_pbm

    qapp.clipboard().setText("Tiếng Việt có dấu: 🇻🇳")
    win.paste_clipboard_to_phone()
    mock_pbm.send_text_with_paste_sync.assert_called_once_with(
        "Tiếng Việt có dấu: 🇻🇳", mock_hid
    )


def test_window_productivity_shortcuts(qapp):
    from PySide6.QtGui import QKeySequence
    win = AircontrolWindow()

    # Collect all actions and their shortcuts
    all_shortcuts = []
    for act in win.actions():
        for seq in act.shortcuts():
            all_shortcuts.append(seq.toString())

    # Verify required shortcuts are registered
    # 1. Home Screen (Home / Esc)
    assert any("Home" in sc for sc in all_shortcuts)
    assert any("Esc" in sc for sc in all_shortcuts)
    # 2. App Switcher (Alt+Tab / Ctrl+Tab)
    assert any("Alt+Tab" in sc for sc in all_shortcuts)
    assert any("Ctrl+Tab" in sc for sc in all_shortcuts)
    # 3. Lock iPhone (Ctrl+L)
    assert any("Ctrl+L" in sc for sc in all_shortcuts)
    # 4. Screenshot (F12)
    assert any("F12" in sc for sc in all_shortcuts)








