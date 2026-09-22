"""HIDBridge: Translates mouse, gestures, keyboard, and physical buttons into iOS HID reports."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# CoreDevice HID Constants
TOUCHSCREEN_STATE_CONTACT = 194
TOUCHSCREEN_STATE_RELEASE = 2
DIGITIZER_SURFACE_MAIN_TOUCHSCREEN = 257

HID_BUTTON_STATE_DOWN = 1
HID_BUTTON_STATE_UP = 0

NAMED_BUTTONS: Dict[str, Tuple[int, int, float]] = {
    "home": (12, 64, 0.05),
    "lock": (12, 48, 0.5),
    "power": (12, 48, 0.5),
    "volume-up": (12, 233, 0.05),
    "volume-down": (12, 234, 0.05),
    "mute": (12, 226, 0.05),
    "siri": (12, 207, 1.0),
}


def normalize_coordinates(x: float, y: float, clamp: bool = True) -> Tuple[int, int]:
    """Convert normalized [0.0..1.0] coordinates to iOS 16-bit UInt16 [0..65535] touch space."""
    if clamp:
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
    ix = int(round(x * 65535))
    iy = int(round(y * 65535))
    return ix, iy


class HIDBridge:
    """Bridges input actions (touch, scroll, buttons, keys) to CoreDevice RemoteXPC HID services."""

    def __init__(
        self,
        rsd: Any = None,
        indigo_svc: Any = None,
        uhs_svc: Any = None,
    ) -> None:
        self.rsd = rsd
        self._indigo = indigo_svc
        self._uhs = uhs_svc
        self._keyboard_id: Optional[int] = None
        self._lock = asyncio.Lock()

    async def ensure_services(self) -> None:
        """Lazily initialize and connect IndigoHID and UniversalHID services."""
        if self._indigo is not None and self._uhs is not None:
            return

        if self.rsd is None:
            return

        try:
            from pymobiledevice3.remote.core_device.hid_service import (
                IndigoHIDService,
                UniversalHIDServiceService,
            )

            if self._indigo is None:
                self._indigo = IndigoHIDService(self.rsd)
                await self._indigo.connect()

            if self._uhs is None:
                self._uhs = UniversalHIDServiceService(self.rsd)
                await self._uhs.connect()

            logger.info("CoreDevice HID services connected successfully")
        except Exception as e:
            logger.warning("Failed to initialize CoreDevice HID services: %s", e)

    async def send_button(self, name: str, state: str = "press") -> bool:
        """Send hardware button press (home, lock/power, volume-up, volume-down, mute, siri)."""
        clean_name = name.lower().strip()
        if clean_name not in NAMED_BUTTONS:
            logger.warning("Unknown button requested: %s", name)
            return False

        await self.ensure_services()
        if self._indigo is None:
            return False

        usage_page, usage_code, hold_time = NAMED_BUTTONS[clean_name]
        async with self._lock:
            if state == "press":
                await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_DOWN)
                await asyncio.sleep(hold_time)
                await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_UP)
            elif state == "down":
                await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_DOWN)
            elif state == "up":
                await self._indigo.send_button(usage_page, usage_code, HID_BUTTON_STATE_UP)
        return True

    async def send_touch(self, action: str, x: float, y: float) -> bool:
        """Send touch event: action in ('down', 'move', 'up', 'cancel', 'tap', 'contact', 'release')."""
        await self.ensure_services()
        if self._uhs is None:
            return False

        ix, iy = normalize_coordinates(x, y)
        action_lower = action.lower()

        async with self._lock:
            if action_lower in ("down", "move", "contact"):
                await self._uhs.send_touchscreen(
                    TOUCHSCREEN_STATE_CONTACT,
                    ix,
                    iy,
                    service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                )
            elif action_lower in ("up", "cancel", "release"):
                await self._uhs.send_touchscreen(
                    TOUCHSCREEN_STATE_RELEASE,
                    ix,
                    iy,
                    service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                )
            elif action_lower == "tap":
                await self._uhs.send_touchscreen(
                    TOUCHSCREEN_STATE_CONTACT,
                    ix,
                    iy,
                    service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                )
                await asyncio.sleep(0.05)
                await self._uhs.send_touchscreen(
                    TOUCHSCREEN_STATE_RELEASE,
                    ix,
                    iy,
                    service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
                )
        return True

    async def send_drag(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        steps: int = 5,
        duration: float = 0.1,
    ) -> None:
        """Interpolate smooth drag gesture between two points."""
        await self.send_touch("down", start_x, start_y)
        step_interval = duration / max(steps, 1)
        for i in range(1, steps + 1):
            curr_x = start_x + (end_x - start_x) * (i / steps)
            curr_y = start_y + (end_y - start_y) * (i / steps)
            await asyncio.sleep(step_interval)
            await self.send_touch("move", curr_x, curr_y)
        await self.send_touch("up", end_x, end_y)

    async def send_scroll(self, delta_y: float, x: float = 0.5, y: float = 0.5) -> None:
        """Convert mouse wheel delta into a natural touch drag swipe."""
        # Scrolling down on mouse wheel moves page up (finger drags up)
        drag_distance = 0.15 if abs(delta_y) > 0 else 0.05
        direction = -1.0 if delta_y > 0 else 1.0
        start_y = max(0.2, min(0.8, y))
        end_y = max(0.05, min(0.95, start_y + direction * drag_distance))
        await self.send_drag(x, start_y, x, end_y, steps=6, duration=0.1)
