"""Tests for macOS Xcode Simulator custom titlebar."""

import os
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from aircontrol.ui.simulator_titlebar import SimulatorTitleBar


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_simulator_titlebar_creation(qapp):
    bar = SimulatorTitleBar(device_name="iPhone 17 Pro Max")
    assert bar is not None
    assert bar.lbl_title.text() == "iPhone 17 Pro Max"
    assert bar.btn_close is not None
    assert bar.btn_min is not None
    assert bar.btn_max is not None
    assert bar.btn_camera is not None
    assert bar.btn_audio is not None
    assert hasattr(bar, "btn_more") and bar.btn_more is not None


def test_simulator_titlebar_streamlined_layout(qapp):
    """Verify only 3 essential action buttons are visible on the right."""
    bar = SimulatorTitleBar(device_name="iPhone 16 Pro")
    assert bar.btn_audio.isHidden() is False
    assert bar.btn_camera.isHidden() is False
    assert bar.btn_more.isHidden() is False

    # Secondary buttons should be hidden to avoid clutter/overflow
    assert bar.btn_rotate.isHidden() is True
    assert bar.btn_keyboard.isHidden() is True
    assert bar.btn_borderless.isHidden() is True
    assert bar.btn_dim.isHidden() is True
    assert bar.btn_lock.isHidden() is True


def test_simulator_titlebar_more_menu_and_signals(qapp):
    """Verify more options menu triggers appropriate actions and signals."""
    bar = SimulatorTitleBar(device_name="iPhone 16 Pro")
    bar.setup_skins_menu(["iphone-16-pro-natural", "iphone-16-pro-black", "stage-manager-clean"], "iphone-16-pro-natural")

    skin_selected = []
    bar.skin_selected.connect(lambda s: skin_selected.append(s))

    # Trigger skin change from menu
    bar.trigger_skin_selection("stage-manager-clean")
    assert len(skin_selected) == 1
    assert skin_selected[0] == "stage-manager-clean"


def test_simulator_titlebar_dim_screen_signal(qapp):
    bar = SimulatorTitleBar(device_name="iPhone 17 Pro Max")
    signal_emitted = []
    bar.dim_screen_requested.connect(lambda: signal_emitted.append(True))
    bar.dim_screen_requested.emit()
    assert len(signal_emitted) == 1


def test_simulator_titlebar_telemetry_updates(qapp):
    bar = SimulatorTitleBar(device_name="iPhone 17 Pro Max")
    bar.set_device_info("iPhone 16 Pro", "iOS 18.1 • Sẵn sàng")
    assert bar.lbl_title.text() == "iPhone 16 Pro"
    assert "iOS 18.1" in bar.lbl_sub.text()

    bar.set_telemetry(fps=60, width=1296, height=2816)
    assert "60 FPS" in bar.lbl_sub.text()
    assert "1296x2816" in bar.lbl_sub.text()


def test_simulator_titlebar_home_and_app_switcher_signals(qapp):
    bar = SimulatorTitleBar(device_name="iPhone 16 Pro")
    home_emitted = []
    switcher_emitted = []
    bar.home_requested.connect(lambda: home_emitted.append(True))
    bar.app_switcher_requested.connect(lambda: switcher_emitted.append(True))

    bar.home_requested.emit()
    assert len(home_emitted) == 1

    bar.app_switcher_requested.emit()
    assert len(switcher_emitted) == 1


def test_traffic_light_group_hover(qapp):
    bar = SimulatorTitleBar(device_name="iPhone 16 Pro")
    assert bar.traffic_lights is not None
    assert bar.btn_close._show_glyph is False
    assert bar.btn_min._show_glyph is False
    assert bar.btn_max._show_glyph is False

    # Simulate group hover
    bar.traffic_lights.set_group_hover(True)
    assert bar.btn_close._show_glyph is True
    assert bar.btn_min._show_glyph is True
    assert bar.btn_max._show_glyph is True

    # Simulate group leave
    bar.traffic_lights.set_group_hover(False)
    assert bar.btn_close._show_glyph is False
    assert bar.btn_min._show_glyph is False
    assert bar.btn_max._show_glyph is False


def test_monochrome_icons_generation(qapp):
    from aircontrol.ui.icons import get_monochrome_icon
    for icon_name in ["device", "home", "app_switcher", "frame", "rotate", "keyboard", "moon", "lock", "check"]:
        icon = get_monochrome_icon(icon_name)
        assert icon is not None
        assert not icon.isNull()
        pix = icon.pixmap(16, 16)
        assert not pix.isNull()


