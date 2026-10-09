"""USB HID keyboard usage code definitions and Qt Key mapping."""

from __future__ import annotations

from typing import Dict, Optional
from PySide6.QtCore import Qt

from pymobiledevice3.remote.core_device.hid_service import (
    KEY_0,
    KEY_1,
    KEY_2,
    KEY_3,
    KEY_4,
    KEY_5,
    KEY_6,
    KEY_7,
    KEY_8,
    KEY_9,
    KEY_A,
    KEY_APOSTROPHE,
    KEY_B,
    KEY_BACKSLASH,
    KEY_BACKSPACE,
    KEY_C,
    KEY_CAPS_LOCK,
    KEY_COMMA,
    KEY_D,
    KEY_DOT,
    KEY_DOWN,
    KEY_E,
    KEY_ENTER,
    KEY_EQUAL,
    KEY_ESC,
    KEY_F,
    KEY_F1,
    KEY_F2,
    KEY_F3,
    KEY_F4,
    KEY_F5,
    KEY_F6,
    KEY_F7,
    KEY_F8,
    KEY_F9,
    KEY_F10,
    KEY_F11,
    KEY_F12,
    KEY_G,
    KEY_GRAVE,
    KEY_H,
    KEY_I,
    KEY_J,
    KEY_K,
    KEY_L,
    KEY_LBRACKET,
    KEY_LEFT,
    KEY_LEFT_ALT,
    KEY_LEFT_CTRL,
    KEY_LEFT_GUI,
    KEY_LEFT_SHIFT,
    KEY_M,
    KEY_MINUS,
    KEY_N,
    KEY_O,
    KEY_P,
    KEY_Q,
    KEY_R,
    KEY_RBRACKET,
    KEY_RIGHT,
    KEY_RIGHT_ALT,
    KEY_RIGHT_CTRL,
    KEY_RIGHT_GUI,
    KEY_RIGHT_SHIFT,
    KEY_S,
    KEY_SEMICOLON,
    KEY_SLASH,
    KEY_SPACE,
    KEY_T,
    KEY_TAB,
    KEY_U,
    KEY_UP,
    KEY_V,
    KEY_W,
    KEY_X,
    KEY_Y,
    KEY_Z,
)

# Additional standard USB HID Usage Page 0x07 codes
KEY_HOME = 74
KEY_PAGE_UP = 75
KEY_DELETE = 76
KEY_END = 77
KEY_PAGE_DOWN = 78

# Map Qt.Key enum to USB HID Usage Codes
QT_KEY_TO_HID: Dict[int, int] = {
    # Alphabet
    Qt.Key.Key_A.value: KEY_A,
    Qt.Key.Key_B.value: KEY_B,
    Qt.Key.Key_C.value: KEY_C,
    Qt.Key.Key_D.value: KEY_D,
    Qt.Key.Key_E.value: KEY_E,
    Qt.Key.Key_F.value: KEY_F,
    Qt.Key.Key_G.value: KEY_G,
    Qt.Key.Key_H.value: KEY_H,
    Qt.Key.Key_I.value: KEY_I,
    Qt.Key.Key_J.value: KEY_J,
    Qt.Key.Key_K.value: KEY_K,
    Qt.Key.Key_L.value: KEY_L,
    Qt.Key.Key_M.value: KEY_M,
    Qt.Key.Key_N.value: KEY_N,
    Qt.Key.Key_O.value: KEY_O,
    Qt.Key.Key_P.value: KEY_P,
    Qt.Key.Key_Q.value: KEY_Q,
    Qt.Key.Key_R.value: KEY_R,
    Qt.Key.Key_S.value: KEY_S,
    Qt.Key.Key_T.value: KEY_T,
    Qt.Key.Key_U.value: KEY_U,
    Qt.Key.Key_V.value: KEY_V,
    Qt.Key.Key_W.value: KEY_W,
    Qt.Key.Key_X.value: KEY_X,
    Qt.Key.Key_Y.value: KEY_Y,
    Qt.Key.Key_Z.value: KEY_Z,
    # Numbers
    Qt.Key.Key_0.value: KEY_0,
    Qt.Key.Key_1.value: KEY_1,
    Qt.Key.Key_2.value: KEY_2,
    Qt.Key.Key_3.value: KEY_3,
    Qt.Key.Key_4.value: KEY_4,
    Qt.Key.Key_5.value: KEY_5,
    Qt.Key.Key_6.value: KEY_6,
    Qt.Key.Key_7.value: KEY_7,
    Qt.Key.Key_8.value: KEY_8,
    Qt.Key.Key_9.value: KEY_9,
    # Common Controls
    Qt.Key.Key_Return.value: KEY_ENTER,
    Qt.Key.Key_Enter.value: KEY_ENTER,
    Qt.Key.Key_Escape.value: KEY_ESC,
    Qt.Key.Key_Backspace.value: KEY_BACKSPACE,
    Qt.Key.Key_Tab.value: KEY_TAB,
    Qt.Key.Key_Backtab.value: KEY_TAB,
    Qt.Key.Key_Space.value: KEY_SPACE,
    Qt.Key.Key_Delete.value: KEY_DELETE,
    Qt.Key.Key_Home.value: KEY_HOME,
    Qt.Key.Key_End.value: KEY_END,
    Qt.Key.Key_PageUp.value: KEY_PAGE_UP,
    Qt.Key.Key_PageDown.value: KEY_PAGE_DOWN,
    # Navigation Arrows
    Qt.Key.Key_Right.value: KEY_RIGHT,
    Qt.Key.Key_Left.value: KEY_LEFT,
    Qt.Key.Key_Down.value: KEY_DOWN,
    Qt.Key.Key_Up.value: KEY_UP,
    # Punctuation & Symbols
    Qt.Key.Key_Minus.value: KEY_MINUS,
    Qt.Key.Key_Equal.value: KEY_EQUAL,
    Qt.Key.Key_BracketLeft.value: KEY_LBRACKET,
    Qt.Key.Key_BracketRight.value: KEY_RBRACKET,
    Qt.Key.Key_Backslash.value: KEY_BACKSLASH,
    Qt.Key.Key_Semicolon.value: KEY_SEMICOLON,
    Qt.Key.Key_Apostrophe.value: KEY_APOSTROPHE,
    Qt.Key.Key_QuoteLeft.value: KEY_GRAVE,
    Qt.Key.Key_Comma.value: KEY_COMMA,
    Qt.Key.Key_Period.value: KEY_DOT,
    Qt.Key.Key_Slash.value: KEY_SLASH,
    Qt.Key.Key_CapsLock.value: KEY_CAPS_LOCK,
    # Function Keys
    Qt.Key.Key_F1.value: KEY_F1,
    Qt.Key.Key_F2.value: KEY_F2,
    Qt.Key.Key_F3.value: KEY_F3,
    Qt.Key.Key_F4.value: KEY_F4,
    Qt.Key.Key_F5.value: KEY_F5,
    Qt.Key.Key_F6.value: KEY_F6,
    Qt.Key.Key_F7.value: KEY_F7,
    Qt.Key.Key_F8.value: KEY_F8,
    Qt.Key.Key_F9.value: KEY_F9,
    Qt.Key.Key_F10.value: KEY_F10,
    Qt.Key.Key_F11.value: KEY_F11,
    Qt.Key.Key_F12.value: KEY_F12,
    # Modifiers: Map Windows Control/Meta to Apple Command (GUI) for natural iOS shortcuts
    Qt.Key.Key_Control.value: KEY_LEFT_GUI,
    Qt.Key.Key_Meta.value: KEY_LEFT_GUI,
    Qt.Key.Key_Shift.value: KEY_LEFT_SHIFT,
    Qt.Key.Key_Alt.value: KEY_LEFT_ALT,
}


# Windows OEM / PS/2 Set 1 Hardware Scan Code to USB HID Usage Code
# Independent of OS layout, IME (UniKey/EVKey/Vietnamese Telex), or language settings.
SCANCODE_TO_HID: Dict[int, int] = {
    0x01: KEY_ESC,
    0x02: KEY_1,
    0x03: KEY_2,
    0x04: KEY_3,
    0x05: KEY_4,
    0x06: KEY_5,
    0x07: KEY_6,
    0x08: KEY_7,
    0x09: KEY_8,
    0x0A: KEY_9,
    0x0B: KEY_0,
    0x0C: KEY_MINUS,
    0x0D: KEY_EQUAL,
    0x0E: KEY_BACKSPACE,
    0x0F: KEY_TAB,
    0x10: KEY_Q,
    0x11: KEY_W,
    0x12: KEY_E,
    0x13: KEY_R,
    0x14: KEY_T,
    0x15: KEY_Y,
    0x16: KEY_U,
    0x17: KEY_I,
    0x18: KEY_O,
    0x19: KEY_P,
    0x1A: KEY_LBRACKET,
    0x1B: KEY_RBRACKET,
    0x1C: KEY_ENTER,
    0x1D: KEY_LEFT_GUI,   # Map PC Ctrl to Apple Command (GUI) for iOS shortcuts
    0x1E: KEY_A,
    0x1F: KEY_S,
    0x20: KEY_D,
    0x21: KEY_F,
    0x22: KEY_G,
    0x23: KEY_H,
    0x24: KEY_J,
    0x25: KEY_K,
    0x26: KEY_L,
    0x27: KEY_SEMICOLON,
    0x28: KEY_APOSTROPHE,
    0x29: KEY_GRAVE,
    0x2A: KEY_LEFT_SHIFT,
    0x2B: KEY_BACKSLASH,
    0x2C: KEY_Z,
    0x2D: KEY_X,
    0x2E: KEY_C,
    0x2F: KEY_V,
    0x30: KEY_B,
    0x31: KEY_N,
    0x32: KEY_M,
    0x33: KEY_COMMA,
    0x34: KEY_DOT,
    0x35: KEY_SLASH,
    0x36: KEY_RIGHT_SHIFT,
    0x38: KEY_LEFT_ALT,
    0x39: KEY_SPACE,
    0x3A: KEY_CAPS_LOCK,
    0x3B: KEY_F1,
    0x3C: KEY_F2,
    0x3D: KEY_F3,
    0x3E: KEY_F4,
    0x3F: KEY_F5,
    0x40: KEY_F6,
    0x41: KEY_F7,
    0x42: KEY_F8,
    0x43: KEY_F9,
    0x44: KEY_F10,
    0x57: KEY_F11,
    0x58: KEY_F12,
    # Extended navigation keys (with 0x100 prefix or raw)
    0x148: KEY_UP,
    0x48: KEY_UP,
    0x14B: KEY_LEFT,
    0x4B: KEY_LEFT,
    0x14D: KEY_RIGHT,
    0x4D: KEY_RIGHT,
    0x150: KEY_DOWN,
    0x50: KEY_DOWN,
    0x153: KEY_DELETE,
    0x53: KEY_DELETE,
    0x147: KEY_HOME,
    0x47: KEY_HOME,
    0x14F: KEY_END,
    0x4F: KEY_END,
    0x149: KEY_PAGE_UP,
    0x49: KEY_PAGE_UP,
    0x151: KEY_PAGE_DOWN,
    0x51: KEY_PAGE_DOWN,
    0x11D: KEY_RIGHT_GUI,
    0x138: KEY_RIGHT_ALT,
}


def qt_key_to_hid(key_val: int) -> Optional[int]:
    """Convert Qt.Key integer value to USB HID usage code."""
    return QT_KEY_TO_HID.get(key_val)


def resolve_key_event_to_hid(event: Any) -> Optional[int]:
    """Resolve a QKeyEvent to a USB HID usage code.

    Prioritizes the physical hardware scan code (nativeScanCode) so that
    input is completely independent of the PC's language, layout, or IME (UniKey/EVKey).
    Falls back to Qt.Key mapping when nativeScanCode is 0 (e.g. synthetic test events).
    """
    scancode_fn = getattr(event, "nativeScanCode", None)
    if scancode_fn:
        scancode = scancode_fn()
        if scancode:
            hid = SCANCODE_TO_HID.get(scancode) or SCANCODE_TO_HID.get(scancode & 0xFF)
            if hid is not None:
                return hid

    key_fn = getattr(event, "key", None)
    if key_fn:
        return qt_key_to_hid(key_fn())

    return None
