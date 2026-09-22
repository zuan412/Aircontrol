import os
import pytest

# Ensure offscreen Qt rendering for headless CI / unit test
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from aircontrol.ui.toolbar import AcrylicToolbar
from aircontrol.ui.window import AircontrolWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_toolbar_creation(qapp):
    toolbar = AcrylicToolbar()
    assert toolbar is not None
    assert toolbar.btn_screenshot is not None
    assert toolbar.btn_rotate is not None
    assert toolbar.btn_hud is not None


def test_window_creation(qapp):
    win = AircontrolWindow()
    assert win is not None
    assert "Aircontrol" in win.windowTitle()
    assert win.toolbar is not None
