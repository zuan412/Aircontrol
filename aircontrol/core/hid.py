"""Production-grade iOS HID controller for touch, gestures, and physical buttons."""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import socket
import struct
import time
from typing import Any, Deque, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# CoreDevice HID Constants
TOUCHSCREEN_REPORT_ID = 9
TOUCHSCREEN_STATE_CONTACT = 194
TOUCHSCREEN_STATE_RELEASE = 2
DIGITIZER_SURFACE_MAIN_TOUCHSCREEN = 257

HID_BUTTON_STATE_DOWN = 1
HID_BUTTON_STATE_UP = 2

NAMED_BUTTONS: Dict[str, Tuple[int, int, float]] = {
    "home": (12, 64, 0.05),
    "lock": (12, 48, 0.5),
    "power": (12, 48, 0.5),
    "volume-up": (12, 233, 0.05),
    "volume-down": (12, 234, 0.05),
    "mute": (12, 226, 0.05),
    "siri": (12, 207, 1.0),
    "brightness-up": (12, 111, 0.05),
    "brightness-down": (12, 112, 0.05),
}


def _enable_nodelay(service_wrapper: Any) -> None:
    """Disable Nagle's algorithm on the underlying RemoteXPC TCP socket for minimum latency."""
    try:
        # Ignore unittest mocks
        if hasattr(service_wrapper, "_mock_return_value") or hasattr(service_wrapper, "_mock_wraps"):
            return
        remote_xpc = getattr(service_wrapper, "service", None) or getattr(service_wrapper, "_service", None)
        if remote_xpc is not None:
            writer = getattr(remote_xpc, "writer", None) or getattr(remote_xpc, "_writer", None)
            if writer is not None and hasattr(writer, "get_extra_info"):
                sock = writer.get_extra_info("socket")
                if sock is not None and hasattr(sock, "setsockopt"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    logger.debug("TCP_NODELAY enabled on %s", type(service_wrapper).__name__)
    except Exception as e:
        logger.debug("Could not set TCP_NODELAY on %s: %s", type(service_wrapper).__name__, e)


def build_multi_touch_report(
    state: int,
    x: int,
    y: int,
    contact_id: int = 1,
    timestamp: Optional[int] = None,
) -> bytes:
    """Build a 58-byte mainTouchscreen HID report specifying the contact identifier (1 or 2)."""
    if timestamp is None:
        timestamp = time.monotonic_ns() & ((1 << 48) - 1)
    return (
        bytes([TOUCHSCREEN_REPORT_ID, contact_id & 0xFF, 0x05, state])
        + struct.pack("<HH", x & 0xFFFF, y & 0xFFFF)
        + b"\x00" * 32
        + b"\x02\x00\x00\x00"
        + timestamp.to_bytes(6, "little")
        + b"\x00" * 8
    )


def normalize_coordinates(x: float, y: float, clamp: bool = True) -> Tuple[int, int]:
    """Convert normalized [0.0..1.0] coordinates to iOS 16-bit UInt16 [0..65535] touch space."""
    if clamp:
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
    ix = int(round(x * 65535))
    iy = int(round(y * 65535))
    return ix, iy


class HIDController:
    """High-performance non-blocking touch and button controller for iOS RemoteXPC."""

    def __init__(self, rsd: Any = None, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.rsd = rsd
        self.loop = loop
        self._uhs_touch: Any = None
        self._uhs_keyboard: Any = None
        self._indigo: Any = None
        self._lock = asyncio.Lock()
        self._scroll_lock = asyncio.Lock()
        self._last_scroll_t: float = 0.0
        self._last_move_t: float = 0.0

        # State tracking for fluid gesture mechanics
        self._is_touching: bool = False
        self._touch_down_t: float = 0.0
        self._touch_down_x: int = 0
        self._touch_down_y: int = 0
        self._has_moved: bool = False

        # In-place coalescing queue: prevents queue bloating, lag, and dropped releases
        self._touch_events: Deque[Tuple[str, int, int]] = collections.deque()
        self._touch_event_ready: Optional[asyncio.Event] = None
        self._worker_task: Optional[asyncio.Task[None]] = None

        # Virtual HID Keyboard tracking
        self._keyboard_service_id: Optional[int] = None
        self._pressed_keys: set[int] = set()
        self._keyboard_lock = asyncio.Lock()
        self._muted_speaker_steps: int = 0
        self._dimmed_screen_steps: int = 0

    @property
    def _uhs(self) -> Any:
        """Compatibility property for inspection and backward-compatible tests."""
        return self._uhs_touch

    @_uhs.setter
    def _uhs(self, value: Any) -> None:
        self._uhs_touch = value

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def _touch_worker(self) -> None:
        """Worker that serializes HID touch events with zero lag, instant move coalescing, and no drag release penalty."""
        while True:
            try:
                while not self._touch_events:
                    if self._touch_event_ready is None:
                        return
                    self._touch_event_ready.clear()
                    await self._touch_event_ready.wait()

                action, ix, iy = self._touch_events.popleft()

                if self._uhs_touch is None:
                    await self.ensure_touch_service()

                if self._uhs_touch is not None:
                    if action in ("contact", "down"):
                        self._is_touching = True
                        self._touch_down_t = time.monotonic()
                        self._touch_down_x = ix
                        self._touch_down_y = iy
                        self._has_moved = False

                        async with self._lock:
                            await self._uhs_touch.send_touchscreen(
                                TOUCHSCREEN_STATE_CONTACT,
                                ix,
                                iy,
                                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                            )
                    elif action == "move":
                        if not self._is_touching:
                            self._is_touching = True
                            self._touch_down_t = time.monotonic()
                            self._touch_down_x = ix
                            self._touch_down_y = iy
                            self._has_moved = False
                        else:
                            dx = ix - self._touch_down_x
                            dy = iy - self._touch_down_y
                            if (dx * dx + dy * dy) > 20000:  # Sensitive movement threshold (~141 units)
                                self._has_moved = True

                        # Drain any obsolete pending moves that arrived while worker was busy
                        # to immediately jump to the freshest cursor coordinate without backlog lag
                        while self._touch_events and self._touch_events[0][0] == "move":
                            _, ix, iy = self._touch_events.popleft()
                            dx = ix - self._touch_down_x
                            dy = iy - self._touch_down_y
                            if (dx * dx + dy * dy) > 20000:
                                self._has_moved = True

                        async with self._lock:
                            await self._uhs_touch.send_touchscreen(
                                TOUCHSCREEN_STATE_CONTACT,
                                ix,
                                iy,
                                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                            )
                    elif action in ("release", "up", "cancel"):
                        self._is_touching = False
                        if not self._has_moved:
                            # Static click/tap: ensure minimum contact duration (10ms, ~1 frame) so iOS registers tap
                            elapsed = time.monotonic() - self._touch_down_t
                            if elapsed < 0.010:
                                await asyncio.sleep(0.010 - elapsed)
                        # Drag / swipe / flick: ZERO DELAY! Send release instantly so iOS preserves full flick velocity!
                        async with self._lock:
                            await self._uhs_touch.send_touchscreen(
                                TOUCHSCREEN_STATE_RELEASE,
                                ix,
                                iy,
                                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                            )
                        self._has_moved = False
                    elif action == "tap":
                        async with self._lock:
                            await self._uhs_touch.send_touchscreen(
                                TOUCHSCREEN_STATE_CONTACT,
                                ix,
                                iy,
                                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                            )
                            await asyncio.sleep(0.025)
                            await self._uhs_touch.send_touchscreen(
                                TOUCHSCREEN_STATE_RELEASE,
                                ix,
                                iy,
                                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                            )
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                logger.warning("HID touch connection error, resetting touch service for auto-recovery: %s", e)
                if self._uhs_touch is not None:
                    with contextlib.suppress(Exception):
                        await self._uhs_touch.close()
                    self._uhs_touch = None
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("HID touch worker error: %s", e)

    async def ensure_touch_service(self) -> bool:
        """Lazily initialize and connect UniversalHID touch service."""
        if self._uhs_touch is not None:
            return True
        if self.rsd is None:
            return False

        try:
            from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

            if self._uhs_touch is None:
                self._uhs_touch = UniversalHIDServiceService(self.rsd)
                await self._uhs_touch.connect()
                _enable_nodelay(self._uhs_touch)

            if self._worker_task is None and self.loop and self.loop.is_running():
                if self._touch_event_ready is None:
                    self._touch_event_ready = asyncio.Event()
                self._worker_task = self.loop.create_task(self._touch_worker())

            logger.info("CoreDevice UniversalHID touch service connected successfully")
            return True
        except Exception as e:
            logger.warning("Failed to initialize CoreDevice UniversalHID touch service: %s", e)
            self._uhs_touch = None
            return False

    async def ensure_button_service(self) -> bool:
        """Lazily initialize and connect IndigoHID hardware button service."""
        if self._indigo is not None:
            return True
        if self.rsd is None:
            return False

        try:
            from pymobiledevice3.remote.core_device.hid_service import IndigoHIDService

            if self._indigo is None:
                self._indigo = IndigoHIDService(self.rsd)
                await self._indigo.connect()
                _enable_nodelay(self._indigo)

            logger.info("CoreDevice IndigoHID button service connected successfully")
            return True
        except Exception as e:
            logger.debug("CoreDevice IndigoHID button service not available on this device: %s", e)
            self._indigo = None
            return False

    async def ensure_services(self) -> bool:
        """Lazily initialize both touch and button services independently."""
        touch_ok = await self.ensure_touch_service()
        btn_ok = await self.ensure_button_service()
        return touch_ok or btn_ok

    async def ensure_keyboard_service(self) -> bool:
        """Register host-side virtual HID keyboard with dtuhidd via a dedicated RemoteXPC connection."""
        if self._keyboard_service_id is not None and self._uhs_keyboard is not None:
            return True
        if self.rsd is None:
            return False

        async with self._keyboard_lock:
            if self._keyboard_service_id is not None and self._uhs_keyboard is not None:
                return True
            try:
                from pymobiledevice3.remote.core_device.hid_service import UniversalHIDServiceService

                if self._uhs_keyboard is None:
                    self._uhs_keyboard = UniversalHIDServiceService(self.rsd)
                    await self._uhs_keyboard.connect()
                    _enable_nodelay(self._uhs_keyboard)

                self._keyboard_service_id = await self._uhs_keyboard.create_keyboard_service()
                logger.info("Virtual HID keyboard registered successfully with service_id=%s", self._keyboard_service_id)
                return True
            except Exception as e:
                logger.warning("Failed to register virtual HID keyboard: %s", e)
                if self._uhs_keyboard is not None:
                    with contextlib.suppress(Exception):
                        await self._uhs_keyboard.close()
                    self._uhs_keyboard = None
                self._keyboard_service_id = None
                self._pressed_keys.clear()
                return False

    async def send_key(self, usage_code: int, is_down: bool = True) -> bool:
        """Send virtual keyboard key press (down) or release (up) over dedicated keyboard connection."""
        if not await self.ensure_keyboard_service():
            return False

        async with self._keyboard_lock:
            if is_down:
                self._pressed_keys.add(usage_code)
            else:
                self._pressed_keys.discard(usage_code)

            try:
                assert self._keyboard_service_id is not None
                assert self._uhs_keyboard is not None
                await self._uhs_keyboard.send_keyboard(self._keyboard_service_id, self._pressed_keys)
                return True
            except Exception as e:
                logger.debug("Failed to send key usage %s (down=%s): %s", usage_code, is_down, e)
                # Socket failure: clean up keyboard connection without affecting touch service
                if self._uhs_keyboard is not None:
                    with contextlib.suppress(Exception):
                        await self._uhs_keyboard.close()
                    self._uhs_keyboard = None
                self._keyboard_service_id = None
                self._pressed_keys.clear()
                return False

    async def release_all_keys(self) -> bool:
        """Release all currently held keys (called on focus loss or window hide)."""
        if self._keyboard_service_id is None or not self._pressed_keys:
            self._pressed_keys.clear()
            return True

        async with self._keyboard_lock:
            self._pressed_keys.clear()
            try:
                if self._uhs_keyboard is not None:
                    await self._uhs_keyboard.send_keyboard(self._keyboard_service_id, ())
                return True
            except Exception as e:
                logger.debug("Failed to release all keys: %s", e)
                if self._uhs_keyboard is not None:
                    with contextlib.suppress(Exception):
                        await self._uhs_keyboard.close()
                    self._uhs_keyboard = None
                self._keyboard_service_id = None
                return False

    async def send_ascii_text(self, text: str) -> bool:
        """Type a sequence of ASCII characters into active text field."""
        from pymobiledevice3.remote.core_device.hid_service import ASCII_TO_HID, KEY_LEFT_SHIFT

        if not await self.ensure_keyboard_service():
            return False

        assert self._keyboard_service_id is not None
        assert self._uhs_keyboard is not None
        import unicodedata

        for char in text:
            mapping = ASCII_TO_HID.get(char)
            if not mapping:
                # Decompose unicode character to base ASCII if possible (e.g., 'á' -> 'a', 'đ' -> 'd')
                decomposed = unicodedata.normalize("NFKD", char)
                ascii_base = "".join(c for c in decomposed if not unicodedata.combining(c))
                ascii_base = ascii_base.replace("đ", "d").replace("Đ", "D")
                for sub_char in ascii_base:
                    mapping = ASCII_TO_HID.get(sub_char)
                    if mapping:
                        code, need_shift = mapping
                        keys = [KEY_LEFT_SHIFT, code] if need_shift else [code]
                        try:
                            await self._uhs_keyboard.send_keyboard(self._keyboard_service_id, keys)
                            await asyncio.sleep(0.015)
                            await self._uhs_keyboard.send_keyboard(self._keyboard_service_id, ())
                            await asyncio.sleep(0.010)
                        except Exception as e:
                            logger.debug("Failed to send ASCII char %r: %s", sub_char, e)
                continue
            code, need_shift = mapping
            keys = [KEY_LEFT_SHIFT, code] if need_shift else [code]
            try:
                await self._uhs_keyboard.send_keyboard(self._keyboard_service_id, keys)
                await asyncio.sleep(0.015)
                await self._uhs_keyboard.send_keyboard(self._keyboard_service_id, ())
                await asyncio.sleep(0.010)
            except Exception as e:
                logger.debug("Failed to send ASCII char %r: %s", char, e)
                if self._uhs_keyboard is not None:
                    with contextlib.suppress(Exception):
                        await self._uhs_keyboard.close()
                    self._uhs_keyboard = None
                self._keyboard_service_id = None
                return False
        return True

    async def send_paste_shortcut(self) -> bool:
        """Send Cmd + V virtual keyboard combination to paste clipboard into active input field."""
        if not await self.ensure_keyboard_service():
            return False
        from pymobiledevice3.remote.core_device.hid_service import KEY_LEFT_GUI, KEY_V

        try:
            await self.send_key(KEY_LEFT_GUI, is_down=True)
            await self.send_key(KEY_V, is_down=True)
            await asyncio.sleep(0.04)
            await self.send_key(KEY_V, is_down=False)
            await self.send_key(KEY_LEFT_GUI, is_down=False)
            return True
        except Exception as e:
            logger.debug("Failed to send Cmd+V paste shortcut: %s", e)
            return False

    async def send_unicode_text(self, text: str, pasteboard_mgr: Optional[Any] = None) -> bool:
        """Send text string to active iOS input field.

        If text is purely ASCII, types keystrokes via virtual HID keyboard.
        If text contains Unicode characters (e.g. Vietnamese accents):
        - If pasteboard_mgr is provided: injects via iOS Pasteboard + Cmd+V.
        - Fallback: decomposes accented characters to base ASCII.
        """
        if text.isascii():
            return await self.send_ascii_text(text)

        if pasteboard_mgr is not None:
            try:
                ok = await pasteboard_mgr.send_text_with_paste(text, self)
                if ok:
                    return True
            except Exception as e:
                logger.debug("Unicode text injection via PasteboardManager failed: %s", e)

        # Fallback to ASCII transliteration / decomposition
        return await self.send_ascii_text(text)

    async def send_button(self, name: str, state: str = "press") -> bool:
        """Send hardware button press (home, lock/power, volume-up, volume-down, mute, siri)."""
        clean_name = name.lower().strip()
        if clean_name not in NAMED_BUTTONS:
            logger.warning("Unknown button requested: %s", name)
            return False

        if not await self.ensure_button_service():
            return False

        usage_page, usage_code, hold_time = NAMED_BUTTONS[clean_name]
        async with self._lock:
            try:
                if state == "press":
                    await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_DOWN)
                    await asyncio.sleep(hold_time)
                    await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_UP)
                elif state == "down":
                    await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_DOWN)
                elif state == "up":
                    await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_UP)
                return True
            except Exception as e:
                logger.debug("Failed to send button %s: %s", name, e)
                return False

    async def mute_device_speaker(self, steps: int = 16) -> bool:
        """Silence physical iPhone speaker so audio plays exclusively on laptop speakers."""
        if not await self.ensure_button_service():
            return False
        try:
            for _ in range(steps):
                await self._indigo.send_button(12, 234, HID_BUTTON_STATE_DOWN)
                await asyncio.sleep(0.012)
                await self._indigo.send_button(12, 234, HID_BUTTON_STATE_UP)
                await asyncio.sleep(0.008)
            self._muted_speaker_steps = steps
            logger.info("Physical iPhone speaker silenced for mirroring session (%d steps)", steps)
            return True
        except Exception as e:
            logger.debug("Failed to silence iPhone speaker: %s", e)
            return False

    async def restore_device_speaker(self, steps: int = 8) -> bool:
        """Restore moderate speaker volume on iPhone upon disconnecting or closing."""
        if not self._muted_speaker_steps:
            return True
        self._muted_speaker_steps = 0
        if not await self.ensure_button_service():
            return False
        try:
            for _ in range(steps):
                await self._indigo.send_button(12, 233, HID_BUTTON_STATE_DOWN)
                await asyncio.sleep(0.012)
                await self._indigo.send_button(12, 233, HID_BUTTON_STATE_UP)
                await asyncio.sleep(0.008)
            logger.info("Restored iPhone speaker volume (%d steps)", steps)
            return True
        except Exception as e:
            logger.debug("Failed to restore iPhone speaker volume: %s", e)
            return False

    def mute_device_speaker_sync(self) -> None:
        """Thread-safe non-blocking submission of speaker mute from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.mute_device_speaker(), self.loop)

    def restore_device_speaker_sync(self) -> None:
        """Thread-safe non-blocking submission of speaker volume restore from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.restore_device_speaker(), self.loop)

    async def dim_device_screen(self, steps: int = 16) -> bool:
        """Dim physical iPhone screen brightness to minimum (0%) to save battery and blank display."""
        if not await self.ensure_button_service():
            return False
        try:
            for _ in range(steps):
                await self._indigo.send_button(12, 112, HID_BUTTON_STATE_DOWN)
                await asyncio.sleep(0.012)
                await self._indigo.send_button(12, 112, HID_BUTTON_STATE_UP)
                await asyncio.sleep(0.008)
            self._dimmed_screen_steps = steps
            logger.info("Physical iPhone screen dimmed to minimum (%d steps)", steps)
            return True
        except Exception as e:
            logger.debug("Failed to dim iPhone screen: %s", e)
            return False

    async def restore_device_screen(self, steps: int = 8) -> bool:
        """Restore moderate screen brightness on iPhone upon session exit."""
        if not self._dimmed_screen_steps:
            return True
        self._dimmed_screen_steps = 0
        if not await self.ensure_button_service():
            return False
        try:
            for _ in range(steps):
                await self._indigo.send_button(12, 111, HID_BUTTON_STATE_DOWN)
                await asyncio.sleep(0.012)
                await self._indigo.send_button(12, 111, HID_BUTTON_STATE_UP)
                await asyncio.sleep(0.008)
            logger.info("Restored iPhone screen brightness (%d steps)", steps)
            return True
        except Exception as e:
            logger.debug("Failed to restore iPhone screen brightness: %s", e)
            return False

    def dim_device_screen_sync(self) -> None:
        """Thread-safe non-blocking submission of screen dim from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.dim_device_screen(), self.loop)

    def restore_device_screen_sync(self) -> None:
        """Thread-safe non-blocking submission of screen brightness restore from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.restore_device_screen(), self.loop)

    async def send_touch(self, action: str, norm_x: int | float, norm_y: int | float) -> bool:
        """Send touch event:
        action in ('contact', 'down', 'move', 'release', 'up', 'tap').
        Coordinates can be normalized float [0.0..1.0] or raw uint16 [0..65535].
        """
        if not await self.ensure_touch_service():
            return False

        if isinstance(norm_x, float):
            ix, iy = normalize_coordinates(norm_x, norm_y)
        else:
            ix = max(0, min(65535, int(norm_x)))
            iy = max(0, min(65535, int(norm_y)))

        action_lower = action.lower()

        # Dynamic throttle for touch move events (~125Hz) matching Qt video widget sampling
        if action_lower in ("move", "contact"):
            now = time.monotonic()
            if now - self._last_move_t < 0.008:
                return True
            self._last_move_t = now

        async with self._lock:
            try:
                if action_lower in ("down", "move", "contact"):
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_CONTACT,
                        ix,
                        iy,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                elif action_lower in ("up", "release", "cancel"):
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_RELEASE,
                        ix,
                        iy,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                elif action_lower == "tap":
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_CONTACT,
                        ix,
                        iy,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                    await asyncio.sleep(0.05)
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_RELEASE,
                        ix,
                        iy,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                return True
            except Exception as e:
                logger.debug("Failed to send touch %s: %s", action, e)
                return False

    async def send_home(self) -> bool:
        """Trigger authentic native iOS Home action:
        1. Primary: Native hardware Menu/Home button via IndigoHID (Usage Page 0x0C, Usage 0x40).
           Recognized by all iOS versions and hardware models (including bezel-less iPhones).
        2. Fallback 1: Virtual HID keyboard Cmd + H shortcut.
        3. Fallback 2: Upward digitizer flick gesture.
        """
        # 1. Primary: Native IndigoHID button (100% reliable across all iOS devices)
        if await self.ensure_button_service():
            if await self.send_button("home", "press"):
                return True

        # 2. Fallback 1: Virtual HID keyboard Cmd + H
        if await self.ensure_keyboard_service():
            try:
                from pymobiledevice3.remote.core_device.hid_service import KEY_H, KEY_LEFT_GUI

                await self.send_key(KEY_LEFT_GUI, is_down=True)
                await self.send_key(KEY_H, is_down=True)
                await asyncio.sleep(0.04)
                await self.send_key(KEY_H, is_down=False)
                await self.send_key(KEY_LEFT_GUI, is_down=False)
                return True
            except Exception as e:
                logger.debug("Failed to send keyboard Cmd+H home fallback: %s", e)

        # 3. Fallback 2: Upward digitizer flick gesture
        return await self.send_home_gesture()

    async def send_home_gesture(self, norm_x: int = 32768) -> bool:
        """Execute authentic native iOS Home gesture: rapid upward flick from the bottom digitizer edge."""
        if not await self.ensure_touch_service():
            return False

        # Clear any lingering touch events to prevent queue collisions
        self._touch_events.clear()
        self._is_touching = False

        # Physical SpringBoard SBHomeGesturePanGestureRecognizer trajectory:
        # Rapid upward flick starting at the very bottom edge (65535) and accelerating upward past the home threshold
        steps = [65535, 58000, 46000, 32000, 18000, 8000]
        async with self._lock:
            try:
                for y in steps:
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_CONTACT,
                        norm_x,
                        y,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                    await asyncio.sleep(0.010)
                await self._uhs_touch.send_touchscreen(
                    TOUCHSCREEN_STATE_RELEASE,
                    norm_x,
                    6000,
                    service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                )
                return True
            except Exception as e:
                logger.debug("Failed to send home gesture: %s", e)
                return False

    async def send_unlock_swipe(self) -> bool:
        """Simulate the iOS lock screen swipe-up unlock gesture."""
        if not await self.ensure_touch_service():
            return False

        self._touch_events.clear()
        self._is_touching = False

        mid_x = 32768
        steps = [65300, 52000, 36000, 20000, 10000]
        async with self._lock:
            try:
                for i, y in enumerate(steps):
                    state = TOUCHSCREEN_STATE_RELEASE if i == len(steps) - 1 else TOUCHSCREEN_STATE_CONTACT
                    await self._uhs_touch.send_touchscreen(
                        state,
                        mid_x,
                        y,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                    await asyncio.sleep(0.020)
                return True
            except Exception as e:
                logger.debug("Failed to send unlock swipe: %s", e)
                return False

    async def send_scroll_swipe(
        self,
        norm_x: int,
        norm_y: int,
        scroll_up: bool,
        is_horizontal: bool = False,
    ) -> bool:
        """Smooth inertia wheel scroll with natural iOS physics interpolation and edge clearance."""
        if not await self.ensure_touch_service():
            return False

        async with self._scroll_lock:
            now = time.monotonic()
            elapsed = now - self._last_scroll_t

            # Dynamic acceleration: rapid wheel rolling increases scroll impulse for physical kinetic coasting
            base_delta = 9500
            if elapsed < 0.080:
                base_delta = 14000  # Accelerated fling
            elif elapsed < 0.150:
                base_delta = 11500

            self._last_scroll_t = now

            if is_horizontal:
                # Horizontal scroll: scroll_up=True means scroll left (content moves right -> swipe right)
                delta_x = base_delta if scroll_up else -base_delta
                start_y = norm_y
                end_y = norm_y
                if scroll_up:
                    start_x = min(norm_x, 40000)
                    end_x = min(64000, start_x + delta_x)
                else:
                    start_x = max(norm_x, 25000)
                    end_x = max(1500, start_x + delta_x)
            else:
                # Vertical scroll: scroll_up=True means scroll up (content moves down -> swipe down)
                delta_y = base_delta if scroll_up else -base_delta
                start_x = norm_x
                end_x = norm_x
                if scroll_up:
                    start_y = min(norm_y, 40000)
                    end_y = min(64000, start_y + delta_y)
                else:
                    start_y = max(norm_y, 25000)
                    end_y = max(1500, start_y + delta_y)

            async with self._lock:
                try:
                    # 1. Contact at anchor position
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_CONTACT,
                        start_x,
                        start_y,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                    # 2. Natural damping progression curve (5-step inertia curve for authentic momentum physics)
                    steps = [0.22, 0.48, 0.73, 0.91, 1.0]
                    for fraction in steps:
                        await asyncio.sleep(0.007)
                        curr_x = int(round(start_x + (end_x - start_x) * fraction))
                        curr_y = int(round(start_y + (end_y - start_y) * fraction))
                        await self._uhs_touch.send_touchscreen(
                            TOUCHSCREEN_STATE_CONTACT,
                            curr_x,
                            curr_y,
                            service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                        )
                    # 3. Instant release to trigger native iOS momentum
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_RELEASE,
                        end_x,
                        end_y,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                    return True
                except Exception as e:
                    logger.debug("Scroll swipe error: %s", e)
                    return False

    def send_scroll_swipe_sync(
        self,
        norm_x: int,
        norm_y: int,
        scroll_up: bool,
        is_horizontal: bool = False,
    ) -> None:
        """Thread-safe non-blocking submission of smooth scroll swipe from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.send_scroll_swipe(norm_x, norm_y, scroll_up, is_horizontal),
                self.loop,
            )

    async def send_zoom(self, norm_x: int, norm_y: int, zoom_in: bool) -> bool:
        """Authentic iOS two-finger pinch-to-zoom gesture centered at (norm_x, norm_y)."""
        if not await self.ensure_touch_service():
            return False

        # Clamped center focal point
        cx = max(12000, min(53535, norm_x))
        cy = max(12000, min(53535, norm_y))

        # Radius parameters in 65535 digitizer units (natural human pinch geometry)
        # Zoom in: fingers start close (7000 units) and spread outward to (22000 units)
        # Zoom out: fingers start wide (22000 units) and pinch inward to (7000 units)
        r_start = 7000 if zoom_in else 22000
        r_end = 22000 if zoom_in else 7000
        steps = [0.20, 0.45, 0.70, 0.90, 1.0]

        async with self._lock:
            try:
                # 1. Contact at initial radius for both fingers
                dx_init = int(round(r_start * 0.707))
                dy_init = int(round(r_start * 0.707))
                x1 = max(1000, min(64535, cx - dx_init))
                y1 = max(1000, min(64535, cy - dy_init))
                x2 = max(1000, min(64535, cx + dx_init))
                y2 = max(1000, min(64535, cy + dy_init))

                rpt1 = build_multi_touch_report(TOUCHSCREEN_STATE_CONTACT, x1, y1, contact_id=1)
                rpt2 = build_multi_touch_report(TOUCHSCREEN_STATE_CONTACT, x2, y2, contact_id=2)
                await self._uhs_touch.send_report(DIGITIZER_SURFACE_MAIN_TOUCHSCREEN, rpt1)
                await self._uhs_touch.send_report(DIGITIZER_SURFACE_MAIN_TOUCHSCREEN, rpt2)

                # 2. Smooth progression steps (~65Hz)
                for frac in steps:
                    await asyncio.sleep(0.016)
                    r_curr = int(round(r_start + (r_end - r_start) * frac))
                    dx = int(round(r_curr * 0.707))
                    dy = int(round(r_curr * 0.707))
                    x1 = max(1000, min(64535, cx - dx))
                    y1 = max(1000, min(64535, cy - dy))
                    x2 = max(1000, min(64535, cx + dx))
                    y2 = max(1000, min(64535, cy + dy))
                    rpt1 = build_multi_touch_report(TOUCHSCREEN_STATE_CONTACT, x1, y1, contact_id=1)
                    rpt2 = build_multi_touch_report(TOUCHSCREEN_STATE_CONTACT, x2, y2, contact_id=2)
                    await self._uhs_touch.send_report(DIGITIZER_SURFACE_MAIN_TOUCHSCREEN, rpt1)
                    await self._uhs_touch.send_report(DIGITIZER_SURFACE_MAIN_TOUCHSCREEN, rpt2)

                # 3. Instant release for both fingers
                rpt1_rel = build_multi_touch_report(TOUCHSCREEN_STATE_RELEASE, x1, y1, contact_id=1)
                rpt2_rel = build_multi_touch_report(TOUCHSCREEN_STATE_RELEASE, x2, y2, contact_id=2)
                await self._uhs_touch.send_report(DIGITIZER_SURFACE_MAIN_TOUCHSCREEN, rpt1_rel)
                await self._uhs_touch.send_report(DIGITIZER_SURFACE_MAIN_TOUCHSCREEN, rpt2_rel)
                return True
            except Exception as e:
                logger.debug("Send zoom error: %s", e)
                return False

    def send_zoom_sync(self, norm_x: int, norm_y: int, zoom_in: bool) -> None:
        """Thread-safe non-blocking submission of two-finger zoom from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_zoom(norm_x, norm_y, zoom_in), self.loop)

    async def send_multi_touch(
        self,
        contacts: list[tuple[int, int, int, str]],  # [(contact_id, ix, iy, action), ...]
    ) -> bool:
        """Send simultaneous multi-touch reports for touchscreens and trackpad gestures."""
        if not await self.ensure_touch_service():
            return False

        async with self._lock:
            try:
                for contact_id, ix, iy, action in contacts:
                    state = (
                        TOUCHSCREEN_STATE_RELEASE
                        if action.lower() in ("release", "up", "cancel")
                        else TOUCHSCREEN_STATE_CONTACT
                    )
                    rpt = build_multi_touch_report(state, ix, iy, contact_id=contact_id)
                    await self._uhs_touch.send_report(DIGITIZER_SURFACE_MAIN_TOUCHSCREEN, rpt)
                return True
            except Exception as e:
                logger.debug("Multi-touch send error: %s", e)
                return False

    def send_multi_touch_sync(
        self,
        contacts: list[tuple[int, int, int, str]],
    ) -> None:
        """Thread-safe non-blocking submission of multi-touch events from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_multi_touch(contacts), self.loop)

    async def send_double_tap(self, norm_x: int, norm_y: int) -> bool:
        """Send authentic double tap (e.g. to reset zoom in Photos, Safari, Maps)."""
        if not await self.ensure_touch_service():
            return False
        async with self._lock:
            try:
                # Tap 1
                await self._uhs_touch.send_touchscreen(
                    TOUCHSCREEN_STATE_CONTACT, norm_x, norm_y, service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN
                )
                await asyncio.sleep(0.025)
                await self._uhs_touch.send_touchscreen(
                    TOUCHSCREEN_STATE_RELEASE, norm_x, norm_y, service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN
                )
                # Inter-tap dwell
                await asyncio.sleep(0.060)
                # Tap 2
                await self._uhs_touch.send_touchscreen(
                    TOUCHSCREEN_STATE_CONTACT, norm_x, norm_y, service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN
                )
                await asyncio.sleep(0.025)
                await self._uhs_touch.send_touchscreen(
                    TOUCHSCREEN_STATE_RELEASE, norm_x, norm_y, service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN
                )
                return True
            except Exception as e:
                logger.debug("Double tap error: %s", e)
                return False

    def send_double_tap_sync(self, norm_x: int, norm_y: int) -> None:
        """Thread-safe non-blocking submission of double tap from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_double_tap(norm_x, norm_y), self.loop)

    def send_touch_sync(self, action: str, norm_x: int | float, norm_y: int | float) -> None:
        """Thread-safe non-blocking submission of touch events into coalescing queue."""
        if isinstance(norm_x, float):
            ix, iy = normalize_coordinates(norm_x, norm_y)
        else:
            ix = max(0, min(65535, int(norm_x)))
            iy = max(0, min(65535, int(norm_y)))

        action_lower = action.lower()
        if self.loop and not self.loop.is_closed():
            def enqueue() -> None:
                if self._touch_event_ready is None:
                    self._touch_event_ready = asyncio.Event()
                if self._worker_task is None or self._worker_task.done():
                    self._worker_task = asyncio.create_task(self._touch_worker())

                if action_lower == "move":
                    # Update pending move in-place so queue never lags behind the finger
                    if self._touch_events and self._touch_events[-1][0] in ("contact", "move"):
                        self._touch_events[-1] = (action_lower, ix, iy)
                    else:
                        self._touch_events.append((action_lower, ix, iy))
                elif action_lower in ("contact", "down"):
                    if self._is_touching and self._touch_events and self._touch_events[-1][0] in ("contact", "move"):
                        self._touch_events[-1] = ("move", ix, iy)
                    else:
                        self._touch_events.append((action_lower, ix, iy))
                elif action_lower in ("release", "up", "cancel"):
                    self._touch_events.append(("release", ix, iy))

                self._touch_event_ready.set()

            self.loop.call_soon_threadsafe(enqueue)

    def send_button_sync(self, name: str, state: str = "press") -> None:
        """Thread-safe non-blocking submission of hardware button events from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_button(name, state), self.loop)

    def send_home_sync(self) -> None:
        """Thread-safe non-blocking submission of authentic iOS Home action from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_home(), self.loop)

    def send_home_gesture_sync(self, norm_x: int = 32768) -> None:
        """Thread-safe non-blocking submission of native home flick gesture from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_home(), self.loop)

    def send_unlock_swipe_sync(self) -> None:
        """Thread-safe non-blocking submission of unlock swipe gesture from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_unlock_swipe(), self.loop)

    async def send_app_switcher(self, norm_x: int = 32768) -> bool:
        """Open iOS App Switcher:
        1. Primary: Native double-tap Home button via IndigoHID (standard iOS App Switcher trigger).
        2. Fallback 1: Virtual HID keyboard Cmd + Tab shortcut.
        3. Fallback 2: Upward digitizer edge drag with center dwell/hold.
        """
        # 1. Primary: Native double-tap Home button via IndigoHID
        if await self.ensure_button_service():
            try:
                ok1 = await self.send_button("home", "press")
                await asyncio.sleep(0.08)
                ok2 = await self.send_button("home", "press")
                if ok1 and ok2:
                    return True
            except Exception as e:
                logger.debug("Double home button failed: %s", e)

        # 2. Fallback 1: Virtual HID keyboard Cmd + Tab
        if await self.ensure_keyboard_service():
            try:
                from pymobiledevice3.remote.core_device.hid_service import KEY_LEFT_GUI, KEY_TAB

                await self.send_key(KEY_LEFT_GUI, is_down=True)
                await self.send_key(KEY_TAB, is_down=True)
                await asyncio.sleep(0.04)
                await self.send_key(KEY_TAB, is_down=False)
                await self.send_key(KEY_LEFT_GUI, is_down=False)
                return True
            except Exception as e:
                logger.debug("Keyboard Cmd+Tab app switcher failed: %s", e)

        # 3. Fallback 2: Digitizer drag-and-hold
        if not await self.ensure_touch_service():
            return False

        # Clear any lingering touch events to prevent queue collisions
        self._touch_events.clear()
        self._is_touching = False

        # SpringBoard App Switcher gesture:
        # Drag from bottom edge to center (~36000), dwell/hold for ~240ms with keepalives, then release
        steps = [65535, 58000, 50000, 42000, 36000]
        async with self._lock:
            try:
                for y in steps:
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_CONTACT,
                        norm_x,
                        y,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                    await asyncio.sleep(0.012)
                # Dwell / hold in the center to engage App Switcher card dock with active contact keepalives
                for _ in range(6):
                    await asyncio.sleep(0.040)
                    await self._uhs_touch.send_touchscreen(
                        TOUCHSCREEN_STATE_CONTACT,
                        norm_x,
                        36000,
                        service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                    )
                await asyncio.sleep(0.020)
                await self._uhs_touch.send_touchscreen(
                    TOUCHSCREEN_STATE_RELEASE,
                    norm_x,
                    36000,
                    service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                )
                return True
            except Exception as e:
                logger.debug("Failed to send app switcher: %s", e)
                return False

    def send_app_switcher_sync(self) -> None:
        """Thread-safe non-blocking submission of app switcher command from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_app_switcher(), self.loop)

    def send_key_sync(self, usage_code: int, is_down: bool = True) -> None:
        """Thread-safe non-blocking submission of key event from Qt GUI thread."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_key(usage_code, is_down), self.loop)

    def release_all_keys_sync(self) -> None:
        """Thread-safe non-blocking key release for focusOut events."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.release_all_keys(), self.loop)

    def send_ascii_text_sync(self, text: str) -> None:
        """Thread-safe non-blocking submission of ASCII text sequence."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_ascii_text(text), self.loop)

    def send_paste_shortcut_sync(self) -> None:
        """Thread-safe non-blocking submission of Cmd+V paste shortcut."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_paste_shortcut(), self.loop)

    def send_unicode_text_sync(self, text: str, pasteboard_mgr: Optional[Any] = None) -> None:
        """Thread-safe non-blocking submission of Unicode text sequence."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.send_unicode_text(text, pasteboard_mgr), self.loop)

    async def close(self) -> None:
        """Clean up services and worker task."""
        if self._worker_task is not None:
            self._worker_task.cancel()
            self._worker_task = None
        self._touch_events.clear()
        self._touch_event_ready = None
        if self._indigo is not None:
            with contextlib.suppress(Exception):
                await self.restore_device_speaker()
            with contextlib.suppress(Exception):
                await self.restore_device_screen()
            with contextlib.suppress(Exception):
                await self._indigo.close()
            self._indigo = None
        if self._uhs_touch is not None:
            with contextlib.suppress(Exception):
                await self._uhs_touch.close()
            self._uhs_touch = None
        if self._uhs_keyboard is not None:
            self._pressed_keys.clear()
            self._keyboard_service_id = None
            with contextlib.suppress(Exception):
                await self._uhs_keyboard.close()
            self._uhs_keyboard = None
