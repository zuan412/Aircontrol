"""Tests for the Aircontrol iOS Pasteboard integration and Unicode text injection."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from aircontrol.core.pasteboard import PasteboardManager


@pytest.mark.asyncio
async def test_pasteboard_manager_lifecycle_no_rsd():
    mgr = PasteboardManager(rsd=None)
    assert not await mgr.start()
    assert await mgr.get_text() is None
    assert not await mgr.set_text("test")
    await mgr.close()


@pytest.mark.asyncio
async def test_pasteboard_manager_start_and_close():
    mock_rsd = MagicMock()
    mgr = PasteboardManager(rsd=mock_rsd)

    mock_svc = AsyncMock()
    with patch(
        "pymobiledevice3.remote.core_device.pasteboard_service.PasteboardService",
        return_value=mock_svc,
    ):
        started = await mgr.start()
        assert started
        mock_svc.connect.assert_awaited_once()

        await mgr.close()
        mock_svc.close.assert_awaited_once()
        assert mgr._svc is None


@pytest.mark.asyncio
async def test_pasteboard_manager_start_failure_handled_gracefully():
    mock_rsd = MagicMock()
    mgr = PasteboardManager(rsd=mock_rsd)

    with patch(
        "pymobiledevice3.remote.core_device.pasteboard_service.PasteboardService",
        side_effect=RuntimeError("Unsupported device service"),
    ):
        started = await mgr.start()
        assert not started
        assert mgr._svc is None


@pytest.mark.asyncio
async def test_pasteboard_manager_get_text():
    mock_rsd = MagicMock()
    mgr = PasteboardManager(rsd=mock_rsd)

    mock_svc = AsyncMock()
    mock_svc.get_text.return_value = "Xin chào Việt Nam 🇻🇳"
    mgr._svc = mock_svc

    text = await mgr.get_text()
    assert text == "Xin chào Việt Nam 🇻🇳"
    mock_svc.get_text.assert_awaited_once()

    # When service throws exception
    mock_svc.get_text.side_effect = RuntimeError("Pasteboard read error")
    assert await mgr.get_text() is None


@pytest.mark.asyncio
async def test_pasteboard_manager_set_text():
    mock_rsd = MagicMock()
    mgr = PasteboardManager(rsd=mock_rsd)

    mock_svc = AsyncMock()
    mock_svc.set_text.return_value = {"status": "ok"}
    mgr._svc = mock_svc

    ok = await mgr.set_text("Phở bò Hà Nội")
    assert ok
    mock_svc.set_text.assert_awaited_once_with("Phở bò Hà Nội")

    # When service throws exception
    mock_svc.set_text.side_effect = RuntimeError("Pasteboard write error")
    assert not await mgr.set_text("Error text")


@pytest.mark.asyncio
async def test_pasteboard_manager_send_text_with_paste_via_shortcut():
    mock_rsd = MagicMock()
    mgr = PasteboardManager(rsd=mock_rsd)

    mock_svc = AsyncMock()
    mgr._svc = mock_svc

    mock_hid = AsyncMock()
    mock_hid.send_paste_shortcut.return_value = True

    ok = await mgr.send_text_with_paste("Bánh mì Sài Gòn", mock_hid)
    assert ok
    mock_svc.set_text.assert_awaited_once_with("Bánh mì Sài Gòn")
    mock_hid.send_paste_shortcut.assert_awaited_once()


@pytest.mark.asyncio
async def test_pasteboard_manager_send_text_with_paste_fallback_to_send_key():
    mock_rsd = MagicMock()
    mgr = PasteboardManager(rsd=mock_rsd)

    mock_svc = AsyncMock()
    mgr._svc = mock_svc

    # HID controller without send_paste_shortcut, only send_key
    mock_hid = MagicMock()
    del mock_hid.send_paste_shortcut  # Ensure it doesn't have it
    mock_hid.send_key = AsyncMock(return_value=True)

    ok = await mgr.send_text_with_paste("Cà phê sữa đá", mock_hid)
    assert ok
    mock_svc.set_text.assert_awaited_once_with("Cà phê sữa đá")
    # Must have pressed Cmd (227) and V (25) down and up
    assert mock_hid.send_key.await_count >= 4


@pytest.mark.asyncio
async def test_pasteboard_manager_async_context_manager():
    mock_rsd = MagicMock()
    mock_svc = AsyncMock()

    with patch(
        "pymobiledevice3.remote.core_device.pasteboard_service.PasteboardService",
        return_value=mock_svc,
    ):
        async with PasteboardManager(rsd=mock_rsd) as mgr:
            assert mgr._svc is not None
            mock_svc.connect.assert_awaited_once()

        mock_svc.close.assert_awaited_once()
        assert mgr._svc is None


def test_pasteboard_manager_sync_methods():
    loop = asyncio.new_event_loop()
    mock_rsd = MagicMock()
    mgr = PasteboardManager(rsd=mock_rsd, loop=loop)

    mock_svc = AsyncMock()
    mock_svc.get_text.return_value = "Đà Nẵng"
    mock_svc.set_text.return_value = {"status": "ok"}
    mgr._svc = mock_svc

    mock_hid = AsyncMock()
    mock_hid.send_paste_shortcut.return_value = True

    # Test thread-safe sync execution
    import threading

    def worker():
        loop.run_forever()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    try:
        assert mgr.get_text_sync() == "Đà Nẵng"
        assert mgr.set_text_sync("Huế")
        assert mgr.send_text_with_paste_sync("Hội An", mock_hid)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2.0)
        loop.close()
