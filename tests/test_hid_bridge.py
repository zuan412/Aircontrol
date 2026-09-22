import pytest
from unittest.mock import AsyncMock, MagicMock
from aircontrol.core.hid_bridge import HIDBridge, normalize_coordinates


def test_coordinate_normalization():
    # Test boundary clamping and midpoint
    assert normalize_coordinates(0.0, 0.0) == (0, 0)
    assert normalize_coordinates(1.0, 1.0) == (65535, 65535)
    
    mid_x, mid_y = normalize_coordinates(0.5, 0.5)
    assert 32767 <= mid_x <= 32768
    assert 32767 <= mid_y <= 32768

    # Test clamping outside [0..1]
    assert normalize_coordinates(-0.5, 1.5) == (0, 65535)


@pytest.mark.asyncio
async def test_hid_bridge_send_button():
    mock_indigo = AsyncMock()
    mock_uhs = AsyncMock()
    
    bridge = HIDBridge(indigo_svc=mock_indigo, uhs_svc=mock_uhs)
    
    # Test Home button
    await bridge.send_button("home")
    # Test Volume Up
    await bridge.send_button("volume-up")
    # Test Power/Lock
    await bridge.send_button("power")


@pytest.mark.asyncio
async def test_hid_bridge_send_touch():
    mock_indigo = AsyncMock()
    mock_uhs = AsyncMock()
    
    bridge = HIDBridge(indigo_svc=mock_indigo, uhs_svc=mock_uhs)
    
    # Send touch events
    await bridge.send_touch("down", 0.5, 0.5)
    await bridge.send_touch("move", 0.5, 0.6)
    await bridge.send_touch("up", 0.5, 0.6)


@pytest.mark.asyncio
async def test_hid_bridge_send_scroll():
    mock_indigo = AsyncMock()
    mock_uhs = AsyncMock()
    
    bridge = HIDBridge(indigo_svc=mock_indigo, uhs_svc=mock_uhs)
    
    # Send scroll down (positive delta)
    await bridge.send_scroll(delta_y=120, x=0.5, y=0.5)
