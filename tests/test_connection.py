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

    with patch("aircontrol.core.connection.list_usbmux_devices", new_callable=AsyncMock) as mock_list, \
         patch("pymobiledevice3.pair_records.iter_remote_paired_identifiers", return_value=[]):
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


@pytest.mark.asyncio
async def test_list_wifi_devices():
    mgr = ConnectionManager()

    with patch("aircontrol.core.connection.list_usbmux_devices", new_callable=AsyncMock) as mock_usb, \
         patch("pymobiledevice3.pair_records.iter_remote_paired_identifiers") as mock_iter:
        mock_usb.return_value = []
        mock_iter.return_value = ["00008101-WIFI-TEST"]

        devices = await mgr.list_devices()
        assert len(devices) == 1
        assert devices[0].udid == "00008101-WIFI-TEST"
        assert devices[0].connection_type == "wifi"


@pytest.mark.asyncio
async def test_connect_wifi():
    mgr = ConnectionManager()

    mock_rsd = MagicMock()
    mock_rsd.name = "Wi-Fi iPhone"
    mock_rsd.product_type = "iPhone16,1"
    mock_rsd.product_version = "18.2"
    mock_rsd.udid = "wifi-udid-999"

    mock_ans = MagicMock()
    mock_ans.port = 49152
    mock_addr = MagicMock()
    mock_addr.ip = "192.168.0.197"
    mock_addr.full_ip = "192.168.0.197"
    mock_ans.addresses = [mock_addr]

    mock_tunnel_res = MagicMock()
    mock_tunnel_res.address = "::1"
    mock_tunnel_res.port = 55555

    mock_tunnel_cm = AsyncMock()
    mock_tunnel_cm.__aenter__.return_value = mock_tunnel_res

    with patch("pymobiledevice3.bonjour.browse_remotepairing", new_callable=AsyncMock, return_value=[mock_ans]), \
         patch("pymobiledevice3.remote.tunnel_service.create_core_device_tunnel_service_using_remotepairing", new_callable=AsyncMock) as mock_create_svc, \
         patch("pymobiledevice3.remote.tunnel_service.start_tunnel_over_remotepairing", return_value=mock_tunnel_cm), \
         patch("pymobiledevice3.remote.remote_service_discovery.RemoteServiceDiscoveryService") as mock_rsd_cls:
        
        mock_rsd_instance = AsyncMock()
        mock_rsd_instance.name = "Wi-Fi iPhone"
        mock_rsd_instance.product_type = "iPhone16,1"
        mock_rsd_instance.product_version = "18.2"
        mock_rsd_instance.udid = "wifi-udid-999"
        mock_rsd_instance._require_peer_info.return_value = {"Services": {"com.apple.coredevice.displayservice": {}}}
        mock_rsd_cls.return_value = mock_rsd_instance

        info = await mgr.connect(udid="wifi-udid-999", via_wifi=True)
        assert mgr.is_connected
        assert info.connection_type == "wifi"
        assert info.name == "Wi-Fi iPhone"
        assert info.ios_version == "18.2"

        await mgr.disconnect()
        assert not mgr.is_connected


def test_apple_marketing_name_resolution():
    from aircontrol.core.connection import get_apple_marketing_name
    assert get_apple_marketing_name("iPhone13,4") == "iPhone 12 Pro Max"
    assert get_apple_marketing_name("iPhone14,2") == "iPhone 13 Pro"
    assert get_apple_marketing_name("iPhone15,2") == "iPhone 14 Pro"
    assert get_apple_marketing_name("iPhone16,1") == "iPhone 15 Pro"
    assert get_apple_marketing_name("iPad16,3") == "iPad Pro 11-inch (M4)"
    assert get_apple_marketing_name("iPad14,8") == "iPad Air 11-inch (M2)"
    assert get_apple_marketing_name("UnknownDevice") == "UnknownDevice"


@pytest.mark.asyncio
async def test_list_devices_prioritizes_wifi_over_usb():
    mgr = ConnectionManager()

    mock_usb_dev = MagicMock()
    mock_usb_dev.serial = "00008101-USB-ONLY"
    mock_usb_dev.name = "USB iPhone"
    mock_usb_dev.product_type = "iPhone13,4"

    with patch("aircontrol.core.connection.list_usbmux_devices", new_callable=AsyncMock) as mock_usb, \
         patch("pymobiledevice3.pair_records.iter_remote_paired_identifiers") as mock_iter:
        mock_usb.return_value = [mock_usb_dev]
        mock_iter.return_value = ["DF27B074-WIFI-UUID"]

        # 1. By default, Wi-Fi device is placed first
        devs_wifi_first = await mgr.list_devices(prioritize_wifi=True)
        assert len(devs_wifi_first) == 2
        assert devs_wifi_first[0].connection_type == "wifi"
        assert devs_wifi_first[0].udid == "DF27B074-WIFI-UUID"
        assert devs_wifi_first[1].connection_type == "usb"

        # 2. When prioritize_wifi is False, USB is first
        devs_usb_first = await mgr.list_devices(prioritize_wifi=False)
        assert devs_usb_first[0].connection_type == "usb"
        assert devs_usb_first[1].connection_type == "wifi"


@pytest.mark.asyncio
async def test_connect_wifi_auto_mounts_ddi_when_missing():
    mgr = ConnectionManager()

    mock_ans = MagicMock()
    mock_ans.port = 49152
    mock_addr = MagicMock()
    mock_addr.ip = "192.168.0.197"
    mock_addr.full_ip = "192.168.0.197"
    mock_ans.addresses = [mock_addr]

    mock_tunnel_res = MagicMock()
    mock_tunnel_res.address = "::1"
    mock_tunnel_res.port = 55555
    mock_tunnel_res.auxiliary_metadata = {}

    mock_tunnel_cm = AsyncMock()
    mock_tunnel_cm.__aenter__.return_value = mock_tunnel_res

    # Initial RSD has empty services (DDI unmounted)
    mock_rsd1 = AsyncMock()
    mock_rsd1.name = "Wi-Fi iPhone"
    mock_rsd1.product_type = "iPhone13,4"
    mock_rsd1.product_version = "18.0"
    mock_rsd1.udid = "wifi-udid-123"
    mock_rsd1.service = MagicMock()
    mock_rsd1.service.address = ("::1", 55555)
    mock_rsd1.open_connection = MagicMock()
    mock_rsd1.auxiliary_metadata = {}
    mock_rsd1._require_peer_info.return_value = {"Services": {}}

    # Second RSD after DDI mount has displayservice
    mock_rsd2 = AsyncMock()
    mock_rsd2.name = "Wi-Fi iPhone"
    mock_rsd2.product_type = "iPhone13,4"
    mock_rsd2.product_version = "18.0"
    mock_rsd2.udid = "wifi-udid-123"
    mock_rsd2.service = MagicMock()
    mock_rsd2.service.address = ("::1", 55555)
    mock_rsd2.open_connection = MagicMock()
    mock_rsd2.auxiliary_metadata = {}
    mock_rsd2._require_peer_info.return_value = {
        "Services": {"com.apple.coredevice.displayservice": {"Port": 12345}}
    }

    with patch("pymobiledevice3.bonjour.browse_remotepairing", new_callable=AsyncMock, return_value=[mock_ans]), \
         patch("pymobiledevice3.remote.tunnel_service.create_core_device_tunnel_service_using_remotepairing", new_callable=AsyncMock), \
         patch("pymobiledevice3.remote.tunnel_service.start_tunnel_over_remotepairing", return_value=mock_tunnel_cm), \
         patch("pymobiledevice3.remote.remote_service_discovery.RemoteServiceDiscoveryService", side_effect=[mock_rsd1, mock_rsd2]), \
         patch("pymobiledevice3.services.mobile_image_mounter.auto_mount_personalized", new_callable=AsyncMock) as mock_mount:

        info = await mgr.connect(udid="wifi-udid-123", via_wifi=True)
        assert mgr.is_connected
        assert mock_mount.await_count == 1
        assert mock_rsd1.close.await_count >= 1
        assert mgr.rsd is mock_rsd2

        await mgr.disconnect()


def test_get_local_candidate_ips_includes_target_ip():
    from aircontrol.core.connection import _get_local_candidate_ips
    candidates = _get_local_candidate_ips(target_ip="192.168.1.150")
    assert "192.168.1.150" in candidates
    assert candidates[0] == "192.168.1.150"


@pytest.mark.asyncio
async def test_connect_wifi_with_target_ip():
    mgr = ConnectionManager()

    mock_ans = MagicMock()
    mock_ans.port = 49152
    mock_addr = MagicMock()
    mock_addr.ip = "192.168.1.150"
    mock_addr.full_ip = "192.168.1.150"
    mock_ans.addresses = [mock_addr]

    mock_tunnel_res = MagicMock()
    mock_tunnel_res.address = "::1"
    mock_tunnel_res.port = 55555

    mock_tunnel_cm = AsyncMock()
    mock_tunnel_cm.__aenter__.return_value = mock_tunnel_res

    mock_rsd_instance = AsyncMock()
    mock_rsd_instance.name = "Target IP iPhone"
    mock_rsd_instance.product_type = "iPhone16,1"
    mock_rsd_instance.product_version = "18.2"
    mock_rsd_instance.udid = "wifi-ip-test"
    mock_rsd_instance._require_peer_info.return_value = {"Services": {"com.apple.coredevice.displayservice": {}}}

    with patch("pymobiledevice3.bonjour.browse_remotepairing", new_callable=AsyncMock, return_value=[]), \
         patch("aircontrol.core.connection._probe_unicast_remotepairing", return_value=[mock_ans]), \
         patch("pymobiledevice3.remote.tunnel_service.create_core_device_tunnel_service_using_remotepairing", new_callable=AsyncMock) as mock_create_svc, \
         patch("pymobiledevice3.remote.tunnel_service.start_tunnel_over_remotepairing", return_value=mock_tunnel_cm), \
         patch("pymobiledevice3.remote.remote_service_discovery.RemoteServiceDiscoveryService", return_value=mock_rsd_instance):

        info = await mgr.connect(target_ip="192.168.1.150")
        assert mgr.is_connected
        assert info.connection_type == "wifi"
        assert mock_create_svc.await_count == 1
        args, _ = mock_create_svc.call_args
        assert args[1] == "192.168.1.150"
        assert args[2] == 49152

        await mgr.disconnect()


@pytest.mark.asyncio
async def test_connect_wifi_matches_remote_pair_record():
    mgr = ConnectionManager()

    mock_ans = MagicMock()
    mock_ans.port = 49152
    mock_ans.properties = {"identifier": "opaque-device-id", "authTag": "valid-tag"}
    mock_addr = MagicMock()
    mock_addr.ip = "192.168.1.100"
    mock_addr.full_ip = "192.168.1.100"
    mock_ans.addresses = [mock_addr]

    mock_tunnel_res = MagicMock()
    mock_tunnel_res.address = "::1"
    mock_tunnel_res.port = 55555

    mock_tunnel_cm = AsyncMock()
    mock_tunnel_cm.__aenter__.return_value = mock_tunnel_res

    mock_rsd_instance = AsyncMock()
    mock_rsd_instance.name = "Matched iPhone"
    mock_rsd_instance.product_type = "iPhone15,2"
    mock_rsd_instance.product_version = "18.1"
    mock_rsd_instance.udid = "00008101-0001111122223333"
    mock_rsd_instance._require_peer_info.return_value = {"Services": {"com.apple.coredevice.displayservice": {}}}

    with patch("pymobiledevice3.bonjour.browse_remotepairing", new_callable=AsyncMock, return_value=[mock_ans]), \
         patch("pymobiledevice3.pair_records.iter_remote_pair_records_by_identifier", return_value=[("00008101-0001111122223333", "dummy.plist", {"peer_alt_irk": b"mock_irk"})]), \
         patch("pymobiledevice3.remote.tunnel_service._match_remote_pair_record", return_value="00008101-0001111122223333") as mock_match, \
         patch("pymobiledevice3.remote.tunnel_service.create_core_device_tunnel_service_using_remotepairing", new_callable=AsyncMock) as mock_create_svc, \
         patch("pymobiledevice3.remote.tunnel_service.start_tunnel_over_remotepairing", return_value=mock_tunnel_cm), \
         patch("pymobiledevice3.remote.remote_service_discovery.RemoteServiceDiscoveryService", return_value=mock_rsd_instance):

        info = await mgr.connect(via_wifi=True)
        assert mgr.is_connected
        assert info.connection_type == "wifi"
        assert mock_match.called
        assert mock_create_svc.await_count == 1
        args, _ = mock_create_svc.call_args
        # Assert resolved UDID is passed rather than empty string
        assert args[0] == "00008101-0001111122223333"
        assert args[1] == "192.168.1.100"

        await mgr.disconnect()


