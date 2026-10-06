"""Tests for the Aircontrol HID touch and button subsystem."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from aircontrol.core.hid import (
    HIDController,
    NAMED_BUTTONS,
    normalize_coordinates,
)


def test_coordinate_normalization():
    # Corner tests
    assert normalize_coordinates(0.0, 0.0) == (0, 0)
    assert normalize_coordinates(1.0, 1.0) == (65535, 65535)

    # Midpoint test
    mx, my = normalize_coordinates(0.5, 0.5)
    assert abs(mx - 32768) <= 1
    assert abs(my - 32768) <= 1

    # Clamping test
    assert normalize_coordinates(-0.5, 1.5) == (0, 65535)
    assert normalize_coordinates(2.0, -1.0) == (65535, 0)


def test_named_buttons_specification():
    expected_buttons = ["home", "lock", "power", "volume-up", "volume-down", "mute", "siri"]
    for btn in expected_buttons:
        assert btn in NAMED_BUTTONS
        page, code, hold = NAMED_BUTTONS[btn]
        assert page == 12
        assert code > 0
        assert hold > 0.0


@pytest.mark.asyncio
async def test_hid_controller_lifecycle():
    ctrl = HIDController()
    assert ctrl.rsd is None
    assert not await ctrl.ensure_services()
    await ctrl.close()


@pytest.mark.asyncio
async def test_hid_controller_buttons_and_touch():
    mock_rsd = MagicMock()
    ctrl = HIDController(rsd=mock_rsd)

    mock_indigo = AsyncMock()
    mock_uhs = AsyncMock()

    with (
        patch("pymobiledevice3.remote.core_device.hid_service.IndigoHIDService", return_value=mock_indigo),
        patch("pymobiledevice3.remote.core_device.hid_service.UniversalHIDServiceService", return_value=mock_uhs),
    ):
        # 1. Hardware buttons
        success_home = await ctrl.send_button("home")
        assert success_home
        assert mock_indigo.send_button.await_count >= 2

        # 2. Touch down, move, release
        success_down = await ctrl.send_touch("contact", 0.5, 0.5)
        assert success_down
        assert mock_uhs.send_touchscreen.await_count == 1

        success_up = await ctrl.send_touch("release", 0.5, 0.5)
        assert success_up
        assert mock_uhs.send_touchscreen.await_count == 2

        # 3. Unlock swipe
        success_swipe = await ctrl.send_unlock_swipe()
        assert success_swipe
        assert mock_uhs.send_touchscreen.await_count >= 7

        await ctrl.close()
        assert ctrl._indigo is None
        assert ctrl._uhs is None


def test_hid_controller_sync_dispatch():
    loop = asyncio.new_event_loop()
    ctrl = HIDController(loop=loop)

    # Verify sync calls do not crash when loop is set
    ctrl.send_touch_sync("contact", 1000, 2000)
    ctrl.send_button_sync("home")
    ctrl.send_unlock_swipe_sync()

    loop.close()


@pytest.mark.asyncio
async def test_hid_tap_micro_movement_preserves_contact_duration():
    ctrl = HIDController()
    ctrl._uhs = AsyncMock()

    # Simulate tap with 100-unit micro-movement (less than 500 threshold)
    ctrl._touch_events.append(("contact", 10000, 10000))
    ctrl._touch_events.append(("move", 10050, 10050))
    ctrl._touch_events.append(("release", 10050, 10050))
    ctrl._touch_event_ready = asyncio.Event()
    ctrl._touch_event_ready.set()

    worker = asyncio.create_task(ctrl._touch_worker())
    await asyncio.sleep(0.08)  # Let worker process contact + move + 45ms sleep + release
    worker.cancel()

    assert ctrl._uhs.send_touchscreen.await_count == 3
    # Check that release was sent
    last_call = ctrl._uhs.send_touchscreen.await_args_list[-1]
    from aircontrol.core.hid import TOUCHSCREEN_STATE_RELEASE
    assert last_call[0][0] == TOUCHSCREEN_STATE_RELEASE
    assert not ctrl._has_moved


def test_qt_key_to_hid_mapping():
    from PySide6.QtCore import Qt
    from aircontrol.core.key_codes import qt_key_to_hid

    # Alphabet
    assert qt_key_to_hid(Qt.Key.Key_A.value) == 4
    assert qt_key_to_hid(Qt.Key.Key_Z.value) == 29

    # Numbers
    assert qt_key_to_hid(Qt.Key.Key_1.value) == 30
    assert qt_key_to_hid(Qt.Key.Key_0.value) == 39

    # Controls
    assert qt_key_to_hid(Qt.Key.Key_Return.value) == 40
    assert qt_key_to_hid(Qt.Key.Key_Escape.value) == 41
    assert qt_key_to_hid(Qt.Key.Key_Backspace.value) == 42
    assert qt_key_to_hid(Qt.Key.Key_Space.value) == 44

    # Modifiers: Control mapped to Command (GUI) for native iOS shortcuts
    assert qt_key_to_hid(Qt.Key.Key_Control.value) == 227
    assert qt_key_to_hid(Qt.Key.Key_Shift.value) == 225


@pytest.mark.asyncio
async def test_hid_controller_keyboard_lifecycle():
    mock_rsd = MagicMock()
    ctrl = HIDController(rsd=mock_rsd)

    mock_uhs = AsyncMock()
    mock_uhs.create_keyboard_service.return_value = 1001

    with (
        patch("pymobiledevice3.remote.core_device.hid_service.IndigoHIDService", return_value=AsyncMock()),
        patch("pymobiledevice3.remote.core_device.hid_service.UniversalHIDServiceService", return_value=mock_uhs),
    ):
        # 1. Ensure keyboard registers service ID
        ok = await ctrl.ensure_keyboard_service()
        assert ok
        assert ctrl._keyboard_service_id == 1001
        assert mock_uhs.create_keyboard_service.await_count == 1

        # 2. Key press (down) adds to pressed keys and sends report
        success_down = await ctrl.send_key(4, is_down=True)  # Key A
        assert success_down
        assert 4 in ctrl._pressed_keys
        mock_uhs.send_keyboard.assert_awaited_with(1001, {4})

        # 3. Another key press (e.g. Command + C)
        await ctrl.send_key(227, is_down=True)  # Key Cmd
        assert ctrl._pressed_keys == {4, 227}
        mock_uhs.send_keyboard.assert_awaited_with(1001, {4, 227})

        # 4. Key release (up)
        await ctrl.send_key(4, is_down=False)
        assert ctrl._pressed_keys == {227}
        mock_uhs.send_keyboard.assert_awaited_with(1001, {227})

        # 5. Release all keys (e.g. on focusOutEvent)
        await ctrl.release_all_keys()
        assert len(ctrl._pressed_keys) == 0
        mock_uhs.send_keyboard.assert_awaited_with(1001, ())

        # 6. Close releases keyboard service tracking
        await ctrl.close()
        assert ctrl._keyboard_service_id is None
        assert ctrl._uhs_keyboard is None


@pytest.mark.asyncio
async def test_keyboard_socket_failure_does_not_break_touch():
    """Adversarial Falsification: Virtual keyboard socket failure must NOT affect touch."""
    mock_rsd = MagicMock()
    ctrl = HIDController(rsd=mock_rsd)

    mock_touch_uhs = AsyncMock()
    mock_kbd_uhs = AsyncMock()
    mock_kbd_uhs.create_keyboard_service.return_value = 2002

    # Provide distinct instances for touch and keyboard
    with (
        patch("pymobiledevice3.remote.core_device.hid_service.IndigoHIDService", return_value=AsyncMock()),
        patch(
            "pymobiledevice3.remote.core_device.hid_service.UniversalHIDServiceService",
            side_effect=[mock_touch_uhs, mock_kbd_uhs],
        ),
    ):
        # 1. Initialize touch service
        assert await ctrl.ensure_services()
        assert ctrl._uhs_touch is mock_touch_uhs

        # 2. Initialize keyboard service
        assert await ctrl.ensure_keyboard_service()
        assert ctrl._uhs_keyboard is mock_kbd_uhs

        # 3. Simulate severe keyboard crash (e.g. RemoteXPC RST / BrokenPipe)
        mock_kbd_uhs.send_keyboard.side_effect = ConnectionResetError("RemoteXPC stream closed")
        kbd_ok = await ctrl.send_key(4, is_down=True)
        assert not kbd_ok  # Keyboard reports failure safely
        assert ctrl._uhs_keyboard is None  # Keyboard cleaned up
        assert ctrl._keyboard_service_id is None

        # 4. CRITICAL: Touch service must remain completely unharmed and functional!
        touch_ok = await ctrl.send_touch("contact", 0.5, 0.5)
        assert touch_ok
        assert ctrl._uhs_touch is mock_touch_uhs
        mock_touch_uhs.send_touchscreen.assert_awaited()

        await ctrl.close()


@pytest.mark.asyncio
async def test_touch_auto_recovery_on_connection_error():
    """Verify that HID touch worker automatically recovers if socket drops."""
    ctrl = HIDController()
    broken_uhs = AsyncMock()
    broken_uhs.send_touchscreen.side_effect = ConnectionResetError("WSAECONNRESET [WinError 10054]")

    ctrl._uhs_touch = broken_uhs
    ctrl._touch_event_ready = asyncio.Event()

    # Enqueue a touch event
    ctrl._touch_events.append(("contact", 1000, 2000))
    ctrl._touch_event_ready.set()

    worker = asyncio.create_task(ctrl._touch_worker())
    await asyncio.sleep(0.05)
    worker.cancel()

    # Worker caught ConnectionResetError, closed broken socket, and set _uhs_touch = None
    assert ctrl._uhs_touch is None
    broken_uhs.close.assert_awaited()


@pytest.mark.asyncio
async def test_mute_and_restore_device_speaker():
    """Verify that mute_device_speaker sends volume-down and restore_device_speaker sends volume-up."""
    ctrl = HIDController()
    mock_indigo = AsyncMock()
    ctrl._indigo = mock_indigo
    ctrl._uhs_touch = AsyncMock()

    # 1. Mute speaker
    muted = await ctrl.mute_device_speaker(steps=4)
    assert muted
    assert ctrl._muted_speaker_steps == 4
    # Check that volume-down was sent (Usage Page 12, Usage 234)
    assert mock_indigo.send_button.await_count == 4 * 2  # down + up for each step

    mock_indigo.send_button.reset_mock()

    # 2. Restore speaker
    restored = await ctrl.restore_device_speaker(steps=2)
    assert restored
    assert ctrl._muted_speaker_steps == 0
    # Check that volume-up was sent (Usage Page 12, Usage 233)
    assert mock_indigo.send_button.await_count == 2 * 2  # down + up for each step


@pytest.mark.asyncio
async def test_dim_and_restore_device_screen():
    """Verify that dim_device_screen sends brightness-down and restore_device_screen sends brightness-up."""
    ctrl = HIDController()
    mock_indigo = AsyncMock()
    ctrl._indigo = mock_indigo
    ctrl._uhs_touch = AsyncMock()

    # 1. Dim screen to 0%
    dimmed = await ctrl.dim_device_screen(steps=16)
    assert dimmed
    assert ctrl._dimmed_screen_steps == 16
    # Check that brightness-down was sent (Usage Page 12, Usage 112)
    assert mock_indigo.send_button.await_count == 16 * 2

    mock_indigo.send_button.reset_mock()

    # 2. Restore screen brightness
    restored = await ctrl.restore_device_screen(steps=8)
    assert restored
    assert ctrl._dimmed_screen_steps == 0
    # Check that brightness-up was sent (Usage Page 12, Usage 111)
    assert mock_indigo.send_button.await_count == 8 * 2


@pytest.mark.asyncio
async def test_touch_works_even_if_indigo_button_service_missing():
    """Verify that touch service remains 100% operational even if IndigoHID button service is not available (e.g. over Wi-Fi)."""
    mock_rsd = MagicMock()
    ctrl = HIDController(rsd=mock_rsd)

    mock_uhs = AsyncMock()

    with (
        patch("pymobiledevice3.remote.core_device.hid_service.IndigoHIDService.connect", side_effect=Exception("No such service: com.apple.coredevice.hid.indigo")),
        patch("pymobiledevice3.remote.core_device.hid_service.UniversalHIDServiceService", return_value=mock_uhs),
    ):
        # 1. Touch must succeed despite Indigo failure!
        touch_ok = await ctrl.send_touch("contact", 0.5, 0.5)
        assert touch_ok
        assert ctrl._uhs_touch is mock_uhs
        assert ctrl._indigo is None

        # 2. Button fails gracefully without throwing exception or breaking touch
        btn_ok = await ctrl.send_button("lock")
        assert not btn_ok

        # 3. Subsequent touch still succeeds
        touch_up_ok = await ctrl.send_touch("release", 0.5, 0.5)
        assert touch_up_ok
        assert mock_uhs.send_touchscreen.await_count == 2

        await ctrl.close()


@pytest.mark.asyncio
async def test_hid_send_home_gesture():
    """Verify authentic native iOS Home flick upward trajectory and release."""
    ctrl = HIDController()
    mock_uhs = AsyncMock()
    ctrl._uhs_touch = mock_uhs

    ok = await ctrl.send_home_gesture(norm_x=32768)
    assert ok
    # 6 contact steps + 1 release step = 7 calls
    assert mock_uhs.send_touchscreen.await_count == 7

    from aircontrol.core.hid import TOUCHSCREEN_STATE_CONTACT, TOUCHSCREEN_STATE_RELEASE

    # First call: contact at extreme bottom (y=65535)
    first_call = mock_uhs.send_touchscreen.await_args_list[0]
    assert first_call[0][0] == TOUCHSCREEN_STATE_CONTACT
    assert first_call[0][1] == 32768
    assert first_call[0][2] == 65535

    # Last call: release at y=6000
    last_call = mock_uhs.send_touchscreen.await_args_list[-1]
    assert last_call[0][0] == TOUCHSCREEN_STATE_RELEASE
    assert last_call[0][1] == 32768
    assert last_call[0][2] == 6000


@pytest.mark.asyncio
async def test_hid_send_app_switcher():
    """Verify authentic native iOS App Switcher upward drag with center dwell keepalives."""
    ctrl = HIDController()
    mock_uhs = AsyncMock()
    ctrl._uhs_touch = mock_uhs

    ok = await ctrl.send_app_switcher(norm_x=32768)
    assert ok

    from aircontrol.core.hid import TOUCHSCREEN_STATE_CONTACT, TOUCHSCREEN_STATE_RELEASE

    # 5 upward steps + 6 center dwell keepalives + 1 release = 12 calls
    assert mock_uhs.send_touchscreen.await_count == 12

    # First call: contact at bottom (y=65535)
    first_call = mock_uhs.send_touchscreen.await_args_list[0]
    assert first_call[0][0] == TOUCHSCREEN_STATE_CONTACT
    assert first_call[0][2] == 65535

    # Last call: release at center (y=36000)
    last_call = mock_uhs.send_touchscreen.await_args_list[-1]
    assert last_call[0][0] == TOUCHSCREEN_STATE_RELEASE
    assert last_call[0][2] == 36000


def test_hid_touch_coalescing_queue_bounds():
    """Verify that rapid touch move events coalesce to at most 2 items to prevent lag."""
    loop = asyncio.new_event_loop()
    ctrl = HIDController(loop=loop)
    # Simulate a busy worker that hasn't finished sending yet
    ctrl._worker_task = MagicMock(done=MagicMock(return_value=False))

    # Simulate 20 rapid mouse move events arriving while worker is busy
    ctrl.send_touch_sync("contact", 10000, 10000)
    for i in range(1, 21):
        ctrl.send_touch_sync("move", 10000 + i * 100, 20000 + i * 100)

    # Run pending callbacks scheduled on the loop
    loop.run_until_complete(asyncio.sleep(0.01))

    # Queue length must be strictly bounded to at most 2 items (contact + latest move)
    assert len(ctrl._touch_events) <= 2
    # The last element in queue must be the latest target position
    assert ctrl._touch_events[-1] == ("move", 12000, 22000)

    loop.close()


@pytest.mark.asyncio
async def test_hid_send_home_prefers_button_service():
    """Verify send_home uses IndigoHID button 'home' as primary path."""
    ctrl = HIDController()
    mock_indigo = AsyncMock()
    ctrl._indigo = mock_indigo
    ctrl._uhs_touch = AsyncMock()

    ok = await ctrl.send_home()
    assert ok
    # send_button("home") was called (down + up = 2 calls)
    assert mock_indigo.send_button.await_count == 2
    args_down = mock_indigo.send_button.await_args_list[0][0]
    assert args_down[0] == 12  # Consumer page
    assert args_down[1] == 64  # Usage code 64 (Menu / Home)


@pytest.mark.asyncio
async def test_hid_send_app_switcher_prefers_double_button():
    """Verify send_app_switcher uses double-click of Home button as primary path."""
    ctrl = HIDController()
    mock_indigo = AsyncMock()
    ctrl._indigo = mock_indigo
    ctrl._uhs_touch = AsyncMock()

    ok = await ctrl.send_app_switcher()
    assert ok
    # Double press = 2 * (down + up) = 4 calls
    assert mock_indigo.send_button.await_count == 4


@pytest.mark.asyncio
async def test_hid_multi_touch_and_double_tap():
    ctrl = HIDController()
    mock_uhs = AsyncMock()
    ctrl._uhs_touch = mock_uhs

    # 1. Multi-touch (two fingers)
    contacts = [
        (1, 20000, 20000, "contact"),
        (2, 40000, 40000, "contact"),
    ]
    ok = await ctrl.send_multi_touch(contacts)
    assert ok
    assert mock_uhs.send_report.await_count == 2

    # 2. Double tap
    mock_uhs.reset_mock()
    ok_tap = await ctrl.send_double_tap(32768, 32768)
    assert ok_tap
    # 2 taps * (down + up) = 4 touchscreen calls
    assert mock_uhs.send_touchscreen.await_count == 4


@pytest.mark.asyncio
async def test_hid_send_ascii_text_vietnamese_transliteration():
    ctrl = HIDController()
    mock_uhs = AsyncMock()
    ctrl._uhs_keyboard = mock_uhs
    ctrl._keyboard_service_id = 1

    ok = await ctrl.send_ascii_text("Hà Nội")
    assert ok
    # "Hà Nội" decomposes into "Ha Noi" (6 chars) -> 6 key downs + 6 key ups = 12 calls
    assert mock_uhs.send_keyboard.await_count == 12


@pytest.mark.asyncio
async def test_hid_send_scroll_swipe_five_step_damping():
    """Verify send_scroll_swipe uses 5-step natural damping curve [0.22, 0.48, 0.73, 0.91, 1.0]."""
    ctrl = HIDController()
    mock_uhs = AsyncMock()
    ctrl._uhs_touch = mock_uhs

    ok = await ctrl.send_scroll_swipe(32768, 32768, scroll_up=True)
    assert ok

    from aircontrol.core.hid import TOUCHSCREEN_STATE_CONTACT, TOUCHSCREEN_STATE_RELEASE

    # 1 initial contact + 5 interpolation steps + 1 release = 7 calls
    assert mock_uhs.send_touchscreen.await_count == 7

    # Verify first call is initial contact at start_x, start_y
    first_call = mock_uhs.send_touchscreen.await_args_list[0][0]
    assert first_call[0] == TOUCHSCREEN_STATE_CONTACT
    assert first_call[1] == 32768

    # Verify 5 intermediate contact steps
    for i in range(1, 6):
        step_call = mock_uhs.send_touchscreen.await_args_list[i][0]
        assert step_call[0] == TOUCHSCREEN_STATE_CONTACT

    # Verify final call is release
    release_call = mock_uhs.send_touchscreen.await_args_list[-1][0]
    assert release_call[0] == TOUCHSCREEN_STATE_RELEASE


@pytest.mark.asyncio
async def test_hid_send_paste_shortcut():
    """Verify send_paste_shortcut sends Cmd+V key combination."""
    ctrl = HIDController()
    ctrl.ensure_keyboard_service = AsyncMock(return_value=True)
    ctrl.send_key = AsyncMock(return_value=True)

    from pymobiledevice3.remote.core_device.hid_service import KEY_LEFT_GUI, KEY_V

    ok = await ctrl.send_paste_shortcut()
    assert ok

    # Expected calls: Cmd down, V down, V up, Cmd up
    calls = ctrl.send_key.await_args_list
    assert len(calls) == 4
    assert calls[0][0] == (KEY_LEFT_GUI,) and calls[0][1].get("is_down") is True
    assert calls[1][0] == (KEY_V,) and calls[1][1].get("is_down") is True
    assert calls[2][0] == (KEY_V,) and calls[2][1].get("is_down") is False
    assert calls[3][0] == (KEY_LEFT_GUI,) and calls[3][1].get("is_down") is False


@pytest.mark.asyncio
async def test_hid_send_unicode_text_routes_properly():
    """Verify send_unicode_text uses send_ascii_text for ASCII and pasteboard for Unicode."""
    ctrl = HIDController()
    ctrl.send_ascii_text = AsyncMock(return_value=True)

    # 1. Pure ASCII string -> routes to send_ascii_text
    ok_ascii = await ctrl.send_unicode_text("Hello World 123")
    assert ok_ascii
    ctrl.send_ascii_text.assert_awaited_once_with("Hello World 123")

    # 2. Unicode string with pasteboard_mgr -> routes to pasteboard_mgr.send_text_with_paste
    mock_pbm = AsyncMock()
    mock_pbm.send_text_with_paste.return_value = True

    ok_unicode = await ctrl.send_unicode_text("Tiếng Việt có dấu: 🇻🇳", pasteboard_mgr=mock_pbm)
    assert ok_unicode
    mock_pbm.send_text_with_paste.assert_awaited_once_with("Tiếng Việt có dấu: 🇻🇳", ctrl)

    # 3. Unicode string WITHOUT pasteboard_mgr -> fallback to send_ascii_text
    ctrl.send_ascii_text.reset_mock()
    ok_fallback = await ctrl.send_unicode_text("Đà Nẵng", pasteboard_mgr=None)
    assert ok_fallback
    ctrl.send_ascii_text.assert_awaited_once_with("Đà Nẵng")


def test_hid_unicode_and_paste_sync_dispatch():
    loop = asyncio.new_event_loop()
    ctrl = HIDController(loop=loop)
    ctrl.send_unicode_text = AsyncMock(return_value=True)
    ctrl.send_paste_shortcut = AsyncMock(return_value=True)

    # Verify sync calls do not raise error
    ctrl.send_paste_shortcut_sync()
    ctrl.send_unicode_text_sync("Xin chào")

    loop.close()







