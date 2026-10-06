"""Production-grade iOS Pasteboard manager for bidirectional clipboard sync and Unicode text injection."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PasteboardManager:
    """High-performance iOS Pasteboard client for instant Unicode clipboard exchange."""

    def __init__(
        self,
        rsd: Any = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._rsd = rsd
        self.loop = loop
        self._svc: Any = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Assign or update active asyncio event loop for thread-safe cross-thread calls."""
        self.loop = loop

    async def start(self) -> bool:
        """Initialize and connect to iOS com.apple.coredevice.pasteboardservice."""
        if not self._rsd:
            logger.debug("Cannot start PasteboardManager: RSD service discovery handle is missing")
            return False

        try:
            from pymobiledevice3.remote.core_device.pasteboard_service import PasteboardService

            self._svc = PasteboardService(self._rsd)
            await self._svc.connect()
            logger.info("iOS PasteboardService connected successfully")
            return True
        except Exception as e:
            logger.warning("Failed to connect iOS PasteboardService: %s", e)
            self._svc = None
            return False

    async def get_text(self) -> Optional[str]:
        """Fetch current text content from iOS system clipboard."""
        if self._svc is None:
            if not await self.start():
                return None

        try:
            assert self._svc is not None
            text = await self._svc.get_text()
            return text
        except Exception as e:
            logger.debug("Failed to read iOS pasteboard text: %s", e)
            return None

    async def set_text(self, text: str) -> bool:
        """Write UTF-8 text string into iOS system clipboard."""
        if self._svc is None:
            if not await self.start():
                return False

        try:
            assert self._svc is not None
            await self._svc.set_text(text)
            return True
        except Exception as e:
            logger.debug("Failed to set iOS pasteboard text: %s", e)
            return False

    async def send_text_with_paste(self, text: str, hid_controller: Any) -> bool:
        """Set Unicode text into iOS Pasteboard and simulate Cmd+V to inject text instantly."""
        if not await self.set_text(text):
            logger.debug("send_text_with_paste: failed to write text to iOS pasteboard")
            return False

        # Brief settle time to allow SpringBoard pasteboard daemon to commit the snapshot
        await asyncio.sleep(0.015)

        # 1. Preferred: Dedicated send_paste_shortcut on HIDController
        if hasattr(hid_controller, "send_paste_shortcut"):
            try:
                return await hid_controller.send_paste_shortcut()
            except Exception as e:
                logger.debug("send_paste_shortcut failed: %s", e)

        # 2. Fallback: Direct Cmd + V virtual keyboard combination
        if hasattr(hid_controller, "send_key"):
            try:
                from pymobiledevice3.remote.core_device.hid_service import KEY_LEFT_GUI, KEY_V

                await hid_controller.send_key(KEY_LEFT_GUI, is_down=True)
                await hid_controller.send_key(KEY_V, is_down=True)
                await asyncio.sleep(0.04)
                await hid_controller.send_key(KEY_V, is_down=False)
                await hid_controller.send_key(KEY_LEFT_GUI, is_down=False)
                return True
            except Exception as e:
                logger.debug("Direct Cmd+V send_key fallback failed: %s", e)
                return False

        logger.warning("HID controller has neither send_paste_shortcut nor send_key")
        return False

    async def close(self) -> None:
        """Close Pasteboard service connection without leaking sockets."""
        if self._svc is not None:
            with contextlib.suppress(Exception):
                await self._svc.close()
            self._svc = None

    async def __aenter__(self) -> PasteboardManager:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        await self.close()

    # --- Sync Thread-Safe Helper Methods for Qt GUI Thread ---

    def _get_active_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        if self.loop and self.loop.is_running():
            return self.loop
        try:
            running = asyncio.get_running_loop()
            if running.is_running():
                return running
        except RuntimeError:
            pass
        return None

    def get_text_sync(self, timeout: float = 3.0) -> Optional[str]:
        """Thread-safe synchronous fetch of iOS pasteboard text from GUI thread."""
        loop = self._get_active_loop()
        if not loop:
            return None
        future = asyncio.run_coroutine_threadsafe(self.get_text(), loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            logger.debug("get_text_sync timed out or failed: %s", e)
            return None

    def set_text_sync(self, text: str, timeout: float = 3.0) -> bool:
        """Thread-safe synchronous write to iOS pasteboard from GUI thread."""
        loop = self._get_active_loop()
        if not loop:
            return False
        future = asyncio.run_coroutine_threadsafe(self.set_text(text), loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            logger.debug("set_text_sync timed out or failed: %s", e)
            return False

    def send_text_with_paste_sync(
        self,
        text: str,
        hid_controller: Any,
        timeout: float = 3.0,
    ) -> bool:
        """Thread-safe synchronous Unicode text injection via Cmd+V from GUI thread."""
        loop = self._get_active_loop()
        if not loop:
            return False
        future = asyncio.run_coroutine_threadsafe(
            self.send_text_with_paste(text, hid_controller),
            loop,
        )
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            logger.debug("send_text_with_paste_sync timed out or failed: %s", e)
            return False

    def close_sync(self, timeout: float = 2.0) -> None:
        """Thread-safe synchronous close of PasteboardService."""
        loop = self._get_active_loop()
        if not loop:
            return
        future = asyncio.run_coroutine_threadsafe(self.close(), loop)
        try:
            future.result(timeout=timeout)
        except Exception:
            pass
