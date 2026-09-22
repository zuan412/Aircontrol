import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aircontrol.core.connection import ConnectionManager, DeviceInfo


@pytest.mark.asyncio
async def test_connection_manager_initial_state():
    mgr = ConnectionManager()
    assert not mgr.is_connected
    assert mgr.active_device is None
    assert mgr.rsd is None


@pytest.mark.asyncio
async def test_list_devices_mocked():
    mgr = ConnectionManager()
    
    mock_dev1 = MagicMock()
    mock_dev1.serial = "00008101-001A2B3C4D5E6F"
    mock_dev1.name = "Test iPhone"
    mock_dev1.product_type = "iPhone14,2"

    with patch("aircontrol.core.connection.list_usbmux_devices", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [mock_dev1]
        devices = await mgr.list_devices()
        assert len(devices) == 1
        assert devices[0].udid == "00008101-001A2B3C4D5E6F"
        assert devices[0].name == "Test iPhone"
        assert devices[0].product_type == "iPhone14,2"
        assert devices[0].connection_type == "usb"


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    mgr = ConnectionManager()

    mock_rsd = MagicMock()
    mock_rsd.name = "John's iPhone"
    mock_rsd.product_type = "iPhone15,3"
    mock_rsd.product_version = "17.4"
    mock_rsd.udid = "mock-udid-123"

    mock_tunnel = AsyncMock()
    mock_tunnel.__aenter__.return_value = mock_rsd

    with patch("aircontrol.core.connection.UserspaceRsdTunnel", return_value=mock_tunnel):
        info = await mgr.connect(udid="mock-udid-123")
        assert mgr.is_connected
        assert mgr.active_device is not None
        assert info.name == "John's iPhone"
        assert info.ios_version == "17.4"

        await mgr.disconnect()
        assert not mgr.is_connected
        assert mgr.active_device is None
