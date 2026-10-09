"""Tests for hardware scan code to USB HID mapping and IME decoupling."""

from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from aircontrol.core.key_codes import (
    SCANCODE_TO_HID,
    qt_key_to_hid,
    resolve_key_event_to_hid,
)


def test_scancode_to_hid_table_integrity():
    """Verify that essential alphanumeric, navigation, and control scan codes exist in mapping."""
    # Letters (Windows PS/2 Set 1 scan codes)
    assert SCANCODE_TO_HID[0x1E] == 0x04  # A
    assert SCANCODE_TO_HID[0x30] == 0x05  # B
    assert SCANCODE_TO_HID[0x2E] == 0x06  # C
    assert SCANCODE_TO_HID[0x20] == 0x07  # D
    assert SCANCODE_TO_HID[0x12] == 0x08  # E
    assert SCANCODE_TO_HID[0x10] == 0x14  # Q
    assert SCANCODE_TO_HID[0x11] == 0x1A  # W
    assert SCANCODE_TO_HID[0x1F] == 0x16  # S
    assert SCANCODE_TO_HID[0x2C] == 0x1D  # Z

    # Number keys
    assert SCANCODE_TO_HID[0x02] == 0x1E  # 1
    assert SCANCODE_TO_HID[0x0B] == 0x27  # 0

    # Essential action keys
    assert SCANCODE_TO_HID[0x1C] == 0x28  # Enter
    assert SCANCODE_TO_HID[0x01] == 0x29  # Escape
    assert SCANCODE_TO_HID[0x0E] == 0x2A  # Backspace
    assert SCANCODE_TO_HID[0x0F] == 0x2B  # Tab
    assert SCANCODE_TO_HID[0x39] == 0x2C  # Spacebar

    # Arrows
    assert SCANCODE_TO_HID[0x48] == 0x52  # Up
    assert SCANCODE_TO_HID[0x50] == 0x51  # Down
    assert SCANCODE_TO_HID[0x4B] == 0x50  # Left
    assert SCANCODE_TO_HID[0x4D] == 0x4F  # Right


def test_resolve_key_event_prioritizes_hardware_scancode():
    """Verify resolve_key_event_to_hid uses nativeScanCode even if event.key() is corrupted or unknown."""
    # Simulate a key event where an IME or foreign layout altered the logical key to 0 or unknown,
    # but the physical key pressed was 'A' (scan code 0x1E = 30)
    event = MagicMock(spec=QKeyEvent)
    event.nativeScanCode.return_value = 0x1E
    event.key.return_value = Qt.Key.Key_unknown

    hid = resolve_key_event_to_hid(event)
    assert hid == 0x04  # USB HID Usage code for 'A'


def test_resolve_key_event_fallback_to_qt_key():
    """Verify resolve_key_event_to_hid falls back to qt_key_to_hid when nativeScanCode is 0 or unmapped."""
    event = MagicMock(spec=QKeyEvent)
    event.nativeScanCode.return_value = 0
    event.key.return_value = Qt.Key.Key_B.value

    hid = resolve_key_event_to_hid(event)
    assert hid == 0x05  # USB HID Usage code for 'B'


def test_resolve_key_event_unmapped_returns_none():
    """Verify unmapped keys safely return None."""
    event = MagicMock(spec=QKeyEvent)
    event.nativeScanCode.return_value = 0x9999
    event.key.return_value = 0x9999

    hid = resolve_key_event_to_hid(event)
    assert hid is None
