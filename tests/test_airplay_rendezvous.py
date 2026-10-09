"""Unit tests for AirPlay Rendezvous Discovery module."""

from __future__ import annotations

import asyncio
import plistlib
import re
import socket
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pymobiledevice3.bonjour import (
    QTYPE_A,
    QTYPE_AAAA,
    QTYPE_PTR,
    QTYPE_SRV,
    QTYPE_TXT,
    parse_mdns_message,
)

from aircontrol.core.airplay_rendezvous import (
    AirPlayRendezvous,
    DualServiceMDNSResponder,
    get_clean_local_addresses,
    get_mac_address,
    is_valid_lan_ipv4,
    normalize_hostname,
)


# -----------------------------------------------------------------------------
# 1. Initialization, MAC Address & Hostname Normalization Tests
# -----------------------------------------------------------------------------

def test_get_mac_address_format():
    mac = get_mac_address()
    assert isinstance(mac, str)
    # Standard MAC format: 6 groups of 2 hex digits separated by colons
    assert re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac)


def test_get_mac_address_fallback_on_exception():
    with patch("uuid.getnode", side_effect=RuntimeError("uuid failed")):
        mac = get_mac_address()
        assert re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac)
        # Fallback uses locally administered bit 0x02 for first octet
        assert mac.startswith("02:")


def test_normalize_hostname_rfc_compliance():
    # RFC 1035: Hostname must only contain lowercase ASCII letters, digits, and hyphens
    rfc_pattern = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\.local\.$")

    h1 = normalize_hostname("Aircontrol (PC)")
    assert h1 == "aircontrol-pc.local."
    assert rfc_pattern.match(h1)

    h2 = normalize_hostname("Aircontrol")
    assert h2 == "aircontrol.local."
    assert rfc_pattern.match(h2)

    h3 = normalize_hostname("Living Room (Apple TV)")
    assert h3 == "living-room-apple-tv.local."
    assert rfc_pattern.match(h3)

    # Unicode / Vietnamese diacritics
    h4 = normalize_hostname("iPhone của Nam")
    assert h4 == "iphone-cua-nam.local."
    assert rfc_pattern.match(h4)

    # Strip existing .local. / .local
    h5 = normalize_hostname("test-device.local.")
    assert h5 == "test-device.local."
    assert rfc_pattern.match(h5)

    h6 = normalize_hostname("test-device.local")
    assert h6 == "test-device.local."
    assert rfc_pattern.match(h6)

    # Fallback when all chars are non-alphanumeric
    h7 = normalize_hostname("***@@@!!!")
    assert h7 == "aircontrol-pc.local."
    assert rfc_pattern.match(h7)


def test_airplay_rendezvous_initial_state():
    discovered_cb = MagicMock()
    rendezvous = AirPlayRendezvous(
        port=7000,
        service_name="Aircontrol (PC)",
        on_device_discovered=discovered_cb,
    )

    assert rendezvous.port == 7000
    assert rendezvous.service_name == "Aircontrol (PC)"
    assert rendezvous.hostname == "aircontrol-pc.local."
    assert rendezvous.on_device_discovered is discovered_cb
    assert not rendezvous.is_running
    assert re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", rendezvous.device_id)

    # Required Apple-compatible AirPlay properties
    props = rendezvous.properties
    assert props["deviceid"] == rendezvous.device_id
    assert "features" in props
    assert props["features"] == "0x5A7FFFF7,0x1E"
    assert props["model"] == "AppleTV5,3"
    assert props["srcvers"] == "220.68"
    assert props["flags"] == "0x4"
    assert props["vv"] == "2"
    assert "pk" in props
    assert len(props["pk"]) == 64
    assert "pi" in props

    # Required Apple Screen Mirroring RAOP properties
    raop = rendezvous.raop_properties
    assert raop["ch"] == "2"
    assert raop["cn"] == "0,1,2,3"
    assert raop["da"] == "true"
    assert raop["et"] == "0,3,5"
    assert raop["vv"] == "2"
    assert raop["ft"] == "0x5A7FFFF7,0x1E"
    assert raop["am"] == "AppleTV5,3"
    assert raop["md"] == "0,1,2"
    assert raop["pw"] == "false"
    assert raop["sr"] == "44100"
    assert raop["ss"] == "16"
    assert raop["tp"] == "UDP"
    assert raop["txtvers"] == "1"
    assert raop["sf"] == "0x4"
    assert raop["pk"] == rendezvous.pk


def test_airplay_rendezvous_custom_init():
    custom_props = {
        "deviceid": "AA:BB:CC:DD:EE:FF",
        "features": "0x4",
        "model": "AppleTV6,2",
        "srcvers": "300.0",
        "flags": "0x4",
    }
    rendezvous = AirPlayRendezvous(
        port=7005,
        service_name="Custom AirPlay",
        device_id="AA:BB:CC:DD:EE:FF",
        properties=custom_props,
        hostname="custom-box.local.",
    )

    assert rendezvous.port == 7005
    assert rendezvous.service_name == "Custom AirPlay"
    assert rendezvous.device_id == "AA:BB:CC:DD:EE:FF"
    assert rendezvous.hostname == "custom-box.local."
    assert rendezvous.properties["model"] == "AppleTV6,2"
    assert "pk" in rendezvous.properties
    assert "pi" in rendezvous.properties


# -----------------------------------------------------------------------------
# 2. IP Address Filtering & Network Interface Tests
# -----------------------------------------------------------------------------

def test_is_valid_lan_ipv4():
    # Valid private physical LAN addresses
    assert is_valid_lan_ipv4("192.168.0.198") is True
    assert is_valid_lan_ipv4("192.168.1.1") is True
    assert is_valid_lan_ipv4("10.0.0.15") is True
    assert is_valid_lan_ipv4("10.254.1.2") is True
    assert is_valid_lan_ipv4("172.16.0.1") is True
    assert is_valid_lan_ipv4("172.20.10.2") is True  # iPhone Personal Hotspot
    assert is_valid_lan_ipv4("172.31.255.254") is True

    # Excluded virtual VPNs, APIPA, loopback, CGNAT, public IPs
    assert is_valid_lan_ipv4("26.47.75.199") is False  # Radmin VPN
    assert is_valid_lan_ipv4("169.254.196.137") is False  # APIPA
    assert is_valid_lan_ipv4("169.254.1.1") is False  # APIPA
    assert is_valid_lan_ipv4("127.0.0.1") is False  # Loopback
    assert is_valid_lan_ipv4("100.64.0.1") is False  # Carrier NAT / Tailscale / WARP
    assert is_valid_lan_ipv4("8.8.8.8") is False  # Public internet
    assert is_valid_lan_ipv4("172.32.0.1") is False  # Outside 172.16-31 private block
    assert is_valid_lan_ipv4("invalid-ip") is False
    assert is_valid_lan_ipv4(None) is False  # type: ignore


def test_get_clean_local_addresses_filters_vpn_and_apipa():
    raw_addrs = [
        (socket.AF_INET6, "fdfd::1a2f:4bc7"),  # Radmin IPv6
        (socket.AF_INET, "26.47.75.199"),  # Radmin VPN IPv4
        (socket.AF_INET, "169.254.196.137"),  # APIPA
        (socket.AF_INET, "169.254.22.95"),  # APIPA
        (socket.AF_INET, "192.168.0.198"),  # Physical Realtek Wi-Fi
        (socket.AF_INET, "169.254.28.241"),  # APIPA
        (socket.AF_INET6, "2001:0:14c9:d700:281e:c9a:fec8:f4c0"),  # Teredo
    ]

    clean = get_clean_local_addresses(raw_addrs)
    assert len(clean) == 1
    assert clean[0] == (socket.AF_INET, "192.168.0.198")


def test_get_clean_local_addresses_fallback():
    # When no LAN IPv4 is available, falls back to non-vpn/apipa or 127.0.0.1
    fallback = get_clean_local_addresses([])
    assert fallback == [(socket.AF_INET, "127.0.0.1")]


# -----------------------------------------------------------------------------
# 3. DualServiceMDNSResponder Unit Tests
# -----------------------------------------------------------------------------

def test_dual_service_responder_init_and_names():
    device_id = "72:08:94:93:96:AD"
    responder = DualServiceMDNSResponder(
        service_name="Aircontrol (PC)",
        port=7000,
        device_id=device_id,
        addresses=[(socket.AF_INET, "192.168.0.198")],
    )

    assert responder.hostname == "aircontrol-pc.local."
    assert responder.airplay_service_type == "_airplay._tcp.local."
    assert responder.airplay_instance_name == "Aircontrol (PC)"
    assert responder.airplay_instance_fqdn == "Aircontrol (PC)._airplay._tcp.local."

    # RAOP service: {mac_clean}@{service_name}
    assert responder.raop_service_type == "_raop._tcp.local."
    assert responder.raop_instance_name == "7208949396AD@Aircontrol (PC)"
    assert responder.raop_instance_fqdn == "7208949396AD@Aircontrol (PC)._raop._tcp.local."
    assert responder.addresses == [(socket.AF_INET, "192.168.0.198")]


def test_dual_service_responder_records_parse_cleanly():
    device_id = "72:08:94:93:96:AD"
    airplay_props = {
        "deviceid": device_id,
        "features": "0x5A7FFFF7,0x1E",
        "model": "AppleTV5,3",
        "srcvers": "220.68",
        "flags": "0x4",
        "vv": "2",
        "pk": "abcd" * 16,
        "pi": "uuid-1234",
    }
    raop_props = {
        "ch": "2",
        "cn": "0,1,2,3",
        "da": "true",
        "et": "0,3,5",
        "vv": "2",
        "ft": "0x5A7FFFF7,0x1E",
        "am": "AppleTV5,3",
        "md": "0,1,2",
        "pw": "false",
        "sr": "44100",
        "ss": "16",
        "tp": "UDP",
        "txtvers": "1",
        "sf": "0x4",
        "pk": "abcd" * 16,
    }

    responder = DualServiceMDNSResponder(
        service_name="Aircontrol (PC)",
        port=7000,
        device_id=device_id,
        airplay_properties=airplay_props,
        raop_properties=raop_props,
        addresses=[(socket.AF_INET, "192.168.0.198")],
    )

    answers, additionals = responder._all_records()
    assert len(answers) == 6  # 3 AirPlay (PTR, SRV, TXT) + 3 RAOP (PTR, SRV, TXT)
    assert len(additionals) == 1  # 1 A record for hostname

    msg = responder._build_message(answers, additionals)
    parsed = parse_mdns_message(msg)
    assert len(parsed) == 7

    names_and_types = [(r["name"], r["type"]) for r in parsed]
    assert ("_airplay._tcp.local.", QTYPE_PTR) in names_and_types
    assert ("Aircontrol (PC)._airplay._tcp.local.", QTYPE_SRV) in names_and_types
    assert ("Aircontrol (PC)._airplay._tcp.local.", QTYPE_TXT) in names_and_types
    assert ("_raop._tcp.local.", QTYPE_PTR) in names_and_types
    assert ("7208949396AD@Aircontrol (PC)._raop._tcp.local.", QTYPE_SRV) in names_and_types
    assert ("7208949396AD@Aircontrol (PC)._raop._tcp.local.", QTYPE_TXT) in names_and_types
    assert ("aircontrol-pc.local.", QTYPE_A) in names_and_types

    # Validate SRV target and A record address
    srv_records = [r for r in parsed if r["type"] == QTYPE_SRV]
    for srv in srv_records:
        assert srv["target"] == "aircontrol-pc.local."
        assert srv["port"] == 7000

    a_records = [r for r in parsed if r["type"] == QTYPE_A]
    assert a_records[0]["address"] == "192.168.0.198"


def test_dual_service_responder_query_matching():
    responder = DualServiceMDNSResponder(
        service_name="Aircontrol (PC)",
        port=7000,
        device_id="72:08:94:93:96:AD",
        addresses=[(socket.AF_INET, "192.168.0.198")],
    )

    # AirPlay query matching
    assert responder._matches_airplay("_airplay._tcp.local.", QTYPE_PTR) is True
    assert responder._matches_airplay("Aircontrol (PC)._airplay._tcp.local.", QTYPE_SRV) is True
    assert responder._matches_airplay("Aircontrol (PC)._airplay._tcp.local.", QTYPE_TXT) is True
    assert responder._matches_airplay("_raop._tcp.local.", QTYPE_PTR) is False

    # RAOP query matching
    assert responder._matches_raop("_raop._tcp.local.", QTYPE_PTR) is True
    assert responder._matches_raop("7208949396AD@Aircontrol (PC)._raop._tcp.local.", QTYPE_SRV) is True
    assert responder._matches_raop("7208949396AD@Aircontrol (PC)._raop._tcp.local.", QTYPE_TXT) is True
    assert responder._matches_raop("_airplay._tcp.local.", QTYPE_PTR) is False

    # Hostname A query matching
    assert responder._matches_hostname("aircontrol-pc.local.", QTYPE_A) is True
    assert responder._matches_hostname("aircontrol-pc.local.", QTYPE_AAAA) is True
    assert responder._matches_hostname("other-host.local.", QTYPE_A) is False

    # DNS-SD enumeration query matching
    assert responder._matches_dns_sd_enum("_services._dns-sd._udp.local.", QTYPE_PTR) is True


def test_dual_service_responder_records_for_query():
    responder = DualServiceMDNSResponder(
        service_name="Aircontrol (PC)",
        port=7000,
        device_id="72:08:94:93:96:AD",
        addresses=[(socket.AF_INET, "192.168.0.198")],
    )

    # Query specifically for _airplay._tcp.local.
    answers, additionals = responder._records_for_query([("_airplay._tcp.local.", QTYPE_PTR)])
    assert len(answers) == 3  # AirPlay PTR, SRV, TXT
    assert len(additionals) == 1  # Host A record

    # Query specifically for _raop._tcp.local.
    answers_raop, additionals_raop = responder._records_for_query([("_raop._tcp.local.", QTYPE_PTR)])
    assert len(answers_raop) == 3  # RAOP PTR, SRV, TXT
    assert len(additionals_raop) == 1

    # Query specifically for hostname A record
    answers_host, additionals_host = responder._records_for_query([("aircontrol-pc.local.", QTYPE_A)])
    assert len(answers_host) == 1  # Host A record
    assert len(additionals_host) == 0


@pytest.mark.asyncio
async def test_dual_service_responder_announcement_count_on_start():
    responder = DualServiceMDNSResponder(
        service_name="Aircontrol (PC)",
        port=7000,
        device_id="72:08:94:93:96:AD",
        addresses=[(socket.AF_INET, "192.168.0.198")],
    )

    mock_queue = asyncio.Queue()
    mock_transport = MagicMock()
    mock_sock = MagicMock()
    mock_sock.family = socket.AF_INET

    announce_mock = MagicMock()
    responder._announce = announce_mock

    with patch("aircontrol.core.airplay_rendezvous._open_mdns_sockets", return_value=([(mock_transport, mock_sock)], mock_queue)):
        async with responder:
            assert announce_mock.call_count == 3  # Broadcasted 3 times on start for instant detection

        # Goodbye packet with ttl=0 on exit
        assert announce_mock.call_count == 4
        announce_mock.assert_called_with(ttl=0)


# -----------------------------------------------------------------------------
# 4. HTTP Request Processing & Plist Response Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_get_info_request_with_client_name():
    callback_calls = []

    def on_discovered(ip: str, name: str) -> None:
        callback_calls.append((ip, name))

    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(
            port=0,  # OS assigns free port
            service_name="Aircontrol (PC)",
            on_device_discovered=on_discovered,
        )
        await rendezvous.start()
        assert rendezvous.is_running
        port = rendezvous._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            req = (
                b"GET /info HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"X-Apple-Client-Name: John%27s%20iPhone\r\n"
                b"User-Agent: AirPlay/220.68\r\n"
                b"\r\n"
            )
            writer.write(req)
            await writer.drain()

            resp_data = await asyncio.wait_for(reader.read(8192), timeout=3.0)
            writer.close()
            await writer.wait_closed()

            # Verify HTTP 200 OK
            assert resp_data.startswith(b"HTTP/1.1 200 OK\r\n")
            assert b"Content-Type: text/x-apple-plist+xml" in resp_data
            assert b"Connection: close" in resp_data

            # Parse XML Plist payload
            header_part, body_part = resp_data.split(b"\r\n\r\n", 1)
            plist = plistlib.loads(body_part)
            assert plist["model"] == "AppleTV5,3"
            assert plist["name"] == "Aircontrol (PC)"
            assert plist["srcvers"] == "220.68"
            assert plist["deviceid"] == rendezvous.device_id
            assert plist["pk"] == rendezvous.pk
            assert plist["pi"] == rendezvous.pi
            assert plist["vv"] == 2

            # Verify callback
            assert len(callback_calls) == 1
            ip, name = callback_calls[0]
            assert ip == "127.0.0.1"
            assert name == "John's iPhone"

        finally:
            await rendezvous.stop()


@pytest.mark.asyncio
async def test_http_utf8_percent_encoded_and_raw_client_name():
    callback_calls = []

    def on_discovered(ip: str, name: str) -> None:
        callback_calls.append((ip, name))

    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(
            port=0,
            on_device_discovered=on_discovered,
        )
        await rendezvous.start()
        port = rendezvous._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            req = (
                b"POST /pair-setup HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Length: 4\r\n"
                b"X-Apple-Client-Name: iPhone%20c%E1%BB%A7a%20Nam\r\n"
                b"\r\n"
                b"data"
            )
            writer.write(req)
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=3.0)
            writer.close()
            await writer.wait_closed()

            assert resp.startswith(b"HTTP/1.1 200 OK")
            assert len(callback_calls) == 1
            assert callback_calls[0][1] == "iPhone của Nam"

        finally:
            await rendezvous.stop()


@pytest.mark.asyncio
async def test_http_request_missing_client_name_falls_back_to_iphone():
    callback_calls = []

    def on_discovered(ip: str, name: str) -> None:
        callback_calls.append((ip, name))

    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(
            port=0,
            on_device_discovered=on_discovered,
        )
        await rendezvous.start()
        port = rendezvous._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            req = b"GET /info HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
            writer.write(req)
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=3.0)
            writer.close()
            await writer.wait_closed()

            assert resp.startswith(b"HTTP/1.1 200 OK")
            assert len(callback_calls) == 1
            assert callback_calls[0][1] == "iPhone"

        finally:
            await rendezvous.stop()


@pytest.mark.asyncio
async def test_async_callback_is_awaited():
    called_event = asyncio.Event()

    async def async_discovered(ip: str, name: str) -> None:
        await asyncio.sleep(0.01)
        called_event.set()

    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(
            port=0,
            on_device_discovered=async_discovered,
        )
        await rendezvous.start()
        port = rendezvous._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /info HTTP/1.1\r\n\r\n")
            await writer.drain()

            await asyncio.wait_for(reader.read(4096), timeout=3.0)
            writer.close()
            await writer.wait_closed()

            await asyncio.wait_for(called_event.wait(), timeout=2.0)
            assert called_event.is_set()

        finally:
            await rendezvous.stop()


@pytest.mark.asyncio
async def test_callback_exception_does_not_crash_server():
    def broken_callback(ip: str, name: str) -> None:
        raise RuntimeError("Callback explosion")

    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(
            port=0,
            on_device_discovered=broken_callback,
        )
        await rendezvous.start()
        port = rendezvous._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /info HTTP/1.1\r\n\r\n")
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(4096), timeout=3.0)
            writer.close()
            await writer.wait_closed()

            # Server should still return HTTP 200 OK despite callback error
            assert resp.startswith(b"HTTP/1.1 200 OK")

        finally:
            await rendezvous.stop()


# -----------------------------------------------------------------------------
# 5. Lifecycle & Edge Cases Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_calls_patch_bonjour_multicast():
    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder), \
         patch("aircontrol.core.connection.patch_bonjour_multicast") as mock_patch:
        rendezvous = AirPlayRendezvous(port=0)
        await rendezvous.start()
        mock_patch.assert_called_once()
        await rendezvous.stop()


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle():
    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(port=0)

        # 1. Start
        await rendezvous.start()
        assert rendezvous.is_running
        mock_responder.__aenter__.assert_awaited_once()

        port = rendezvous._server.sockets[0].getsockname()[1]

        # 2. Calling start again is idempotent
        await rendezvous.start()
        assert rendezvous.is_running

        # Verify can connect
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()

        # 3. Stop
        await rendezvous.stop()
        assert not rendezvous.is_running
        mock_responder.__aexit__.assert_awaited_once()

        # 4. Calling stop again is idempotent
        await rendezvous.stop()
        assert not rendezvous.is_running

        # Verify connection rejected after stop
        with pytest.raises((ConnectionRefusedError, OSError)):
            await asyncio.open_connection("127.0.0.1", port)


@pytest.mark.asyncio
async def test_async_context_manager():
    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(port=0)
        async with rendezvous as r:
            assert r.is_running
        assert not rendezvous.is_running


@pytest.mark.asyncio
async def test_client_disconnect_early():
    mock_responder = AsyncMock()
    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(port=0)
        await rendezvous.start()
        port = rendezvous._server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            # Immediate close without sending any bytes
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.05)

            # Server remains healthy for subsequent connections
            reader2, writer2 = await asyncio.open_connection("127.0.0.1", port)
            writer2.write(b"GET /info HTTP/1.1\r\n\r\n")
            await writer2.drain()
            resp = await asyncio.wait_for(reader2.read(4096), timeout=3.0)
            writer2.close()
            await writer2.wait_closed()
            assert resp.startswith(b"HTTP/1.1 200 OK")

        finally:
            await rendezvous.stop()


@pytest.mark.asyncio
async def test_server_bind_failure_cleans_up_mdns():
    mock_responder = AsyncMock()

    # Pre-bind a port on 0.0.0.0 to cause bind failure
    server_temp = await asyncio.start_server(lambda r, w: None, host="0.0.0.0", port=0)
    conflict_port = server_temp.sockets[0].getsockname()[1]

    with patch("aircontrol.core.airplay_rendezvous.DualServiceMDNSResponder", return_value=mock_responder):
        rendezvous = AirPlayRendezvous(port=conflict_port)
        with pytest.raises(OSError):
            await rendezvous.start()

        assert not rendezvous.is_running
        # Responder should be cleaned up if server fails to bind
        mock_responder.__aexit__.assert_awaited_once()

    server_temp.close()
    await server_temp.wait_closed()


# -----------------------------------------------------------------------------
# 6. AircontrolAppRunner Integration Tests
# -----------------------------------------------------------------------------

def test_app_runner_connect_method():
    from aircontrol.__main__ import AircontrolAppRunner

    mock_win = MagicMock()
    runner = AircontrolAppRunner(window=mock_win)

    assert runner.target_ip is None
    assert runner.via_wifi is False

    runner.connect(target_ip="192.168.1.15", via_wifi=True)
    assert runner.target_ip == "192.168.1.15"
    assert runner.via_wifi is True


def test_app_runner_connect_triggers_event():
    from aircontrol.__main__ import AircontrolAppRunner

    mock_win = MagicMock()
    runner = AircontrolAppRunner(window=mock_win)

    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    runner.loop = mock_loop
    mock_event = MagicMock()
    runner._connect_trigger_event = mock_event

    runner.connect(target_ip="192.168.1.88", via_wifi=True)
    mock_loop.call_soon_threadsafe.assert_called_once_with(mock_event.set)
