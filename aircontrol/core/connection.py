"""Device connection manager for USB and Wi-Fi iOS connections."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
import logging
from typing import Any, List, Optional

try:
    from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
except ImportError:
    UserspaceRsdTunnel = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    """Represents an iOS device connected via USB or Wi-Fi."""
    udid: str
    name: str = "iPhone"
    product_type: Optional[str] = None
    ios_version: Optional[str] = None
    connection_type: str = "usb"  # "usb" or "wifi"


async def list_usbmux_devices() -> List[Any]:
    """Helper to query raw devices from pymobiledevice3 usbmuxd."""
    try:
        from pymobiledevice3.usbmux import list_devices
        return await list_devices()
    except Exception as e:
        logger.debug("Failed to list usbmux devices: %s", e)
        return []


class ConnectionManager:
    """Manages iOS device discovery and Userspace RSD Tunnels."""

    def __init__(self) -> None:
        self._exit_stack: Optional[AsyncExitStack] = None
        self._rsd: Any = None
        self._active_device: Optional[DeviceInfo] = None

    @property
    def is_connected(self) -> bool:
        return self._rsd is not None

    @property
    def active_device(self) -> Optional[DeviceInfo]:
        return self._active_device

    @property
    def rsd(self) -> Any:
        return self._rsd

    async def list_devices(self) -> List[DeviceInfo]:
        """List all available iOS devices connected via USB or Wi-Fi."""
        devices: List[DeviceInfo] = []
        raw_devices = await list_usbmux_devices()
        for dev in raw_devices:
            udid = getattr(dev, "serial", "") or getattr(dev, "udid", "")
            if udid:
                devices.append(
                    DeviceInfo(
                        udid=udid,
                        name=getattr(dev, "name", "iPhone"),
                        product_type=getattr(dev, "product_type", None),
                        connection_type="usb",
                    )
                )
        return devices

    async def connect(
        self,
        udid: Optional[str] = None,
        via_wifi: bool = False,
    ) -> DeviceInfo:
        """Connect to an iOS device and establish a userspace RSD tunnel."""
        if self._rsd is not None and self._active_device is not None:
            return self._active_device

        stack = AsyncExitStack()
        try:
            if UserspaceRsdTunnel is None:
                raise RuntimeError("pymobiledevice3 UserspaceRsdTunnel is unavailable")
            # 1. Mount DDI if over USB and lockdown pairing is available
            if not via_wifi:
                try:
                    from pymobiledevice3.lockdown import create_using_usbmux
                    from pymobiledevice3.services.mobile_image_mounter import auto_mount
                    lockdown = await create_using_usbmux(udid)
                    await auto_mount(lockdown)
                except Exception as ddi_err:
                    logger.debug("DDI auto_mount check: %s", ddi_err)

            # 2. Establish Userspace RSD Tunnel
            tunnel = UserspaceRsdTunnel(
                serial=udid,
                autopair=True,
                remotepairing_fallback=True,
            )
            rsd = await stack.enter_async_context(tunnel)

            # Extract device information
            dev_name = getattr(rsd, "name", "iPhone")
            product_type = getattr(rsd, "product_type", "iPhone")
            ios_version = getattr(rsd, "product_version", "17.0")
            actual_udid = getattr(rsd, "udid", udid or "")

            self._rsd = rsd
            self._exit_stack = stack
            self._active_device = DeviceInfo(
                udid=actual_udid,
                name=dev_name,
                product_type=product_type,
                ios_version=ios_version,
                connection_type="wifi" if via_wifi else "usb",
            )
            return self._active_device
        except Exception:
            await stack.aclose()
            raise

    async def disconnect(self) -> None:
        """Close tunnel and cleanup connection."""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._rsd = None
        self._active_device = None
