"""Core engine modules for iOS device management, streaming, and HID control."""

from aircontrol.core.airplay_rendezvous import (
    AirPlayRendezvous,
    DualServiceMDNSResponder,
    get_clean_local_addresses,
    is_valid_lan_ipv4,
    normalize_hostname,
)
from aircontrol.core.connection import ConnectionManager, DeviceInfo
from aircontrol.core.hid import HIDController, normalize_coordinates
from aircontrol.core.pasteboard import PasteboardManager
from aircontrol.core.stream import FastHevcDecoder, ScreenStreamEngine

__all__ = [
    "AirPlayRendezvous",
    "ConnectionManager",
    "DeviceInfo",
    "DualServiceMDNSResponder",
    "FastHevcDecoder",
    "HIDController",
    "PasteboardManager",
    "ScreenStreamEngine",
    "get_clean_local_addresses",
    "is_valid_lan_ipv4",
    "normalize_coordinates",
    "normalize_hostname",
]
