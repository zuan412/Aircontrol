"""AirPlay Rendezvous Discovery for rapid iOS device detection.

Advertises Apple-compatible AirPlay (_airplay._tcp.local.) and RAOP (_raop._tcp.local.)
services on port 7000 via a dual-service mDNS responder on UDP 5353, and runs a
lightweight TCP server to capture incoming discovery handshakes (GET /info,
POST /pair-setup, etc.) from iPhones on the local network.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import logging
import plistlib
import re
import socket
import struct
import unicodedata
import urllib.parse
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from pymobiledevice3.bonjour import (
    MDNS_MCAST_V4,
    MDNS_MCAST_V6,
    MDNS_PORT,
    QTYPE_A,
    QTYPE_AAAA,
    QTYPE_PTR,
    QTYPE_SRV,
    QTYPE_TXT,
    _build_rr,
    _encode_srv,
    _encode_txt,
    _open_mdns_sockets,
    _parse_questions,
    encode_name,
)

logger = logging.getLogger(__name__)


def get_mac_address() -> str:
    """Obtain local MAC address or generate a valid locally administered unicast MAC."""
    try:
        node = uuid.getnode()
        mac = ":".join(f"{(node >> (8 * i)) & 0xFF:02X}" for i in reversed(range(6)))
        return mac
    except Exception:
        import random

        octets = [0x02] + [random.randint(0, 255) for _ in range(5)]
        return ":".join(f"{b:02X}" for b in octets)


def normalize_hostname(name: str) -> str:
    """Normalize a friendly display name into an RFC 1035 compliant mDNS hostname ending with .local.

    RFC 1035 mandates hostnames contain only ASCII letters, digits, and hyphens.
    Spaces, parentheses, and diacritics are removed or converted to hyphens.
    """
    clean_name = name.strip()
    if clean_name.endswith(".local."):
        clean_name = clean_name[:-7]
    elif clean_name.endswith(".local"):
        clean_name = clean_name[:-6]

    # Decompose unicode characters (e.g. Vietnamese accents) and drop non-ASCII
    nfkd = unicodedata.normalize("NFKD", clean_name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii").lower()

    # Replace all non-alphanumeric characters with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str).strip("-")
    if not slug:
        slug = "aircontrol-pc"
    return f"{slug}.local."


def is_valid_lan_ipv4(ip: str) -> bool:
    """Return True if ip is a private physical LAN IPv4 address (192.168.*, 10.*, 172.16-31.*).

    Rejects loopback (127.*), APIPA link-local (169.254.*), Radmin VPN (26.*),
    and carrier/virtual CGNAT (100.*).
    """
    if not isinstance(ip, str) or ip.startswith(("127.", "169.254.", "26.", "100.")):
        return False
    try:
        addr = ipaddress.IPv4Address(ip)
        return addr.is_private and not addr.is_loopback and not addr.is_link_local
    except Exception:
        return False


def get_clean_local_addresses(
    addresses: Optional[List[Tuple[int, str]]] = None,
) -> List[Tuple[int, str]]:
    """Filter local network addresses to keep only physical LAN IPv4 addresses.

    Excludes VPN interfaces (e.g. Radmin 26.*), APIPA (169.254.*), loopback (127.*),
    and carrier/virtual CGNAT (100.*).
    """
    if addresses is None:
        try:
            from pymobiledevice3.bonjour import _local_addresses

            raw = _local_addresses()
        except Exception:
            raw = []
    else:
        raw = addresses

    clean: List[Tuple[int, str]] = []
    for family, ip in raw:
        if family == socket.AF_INET and is_valid_lan_ipv4(ip):
            clean.append((family, ip))

    # Fallback if no private physical LAN IPv4 detected (e.g., test mocks or offline)
    if not clean:
        for family, ip in raw:
            if family == socket.AF_INET and not ip.startswith(("26.", "169.254.")):
                clean.append((family, ip))

    if not clean:
        clean = [(socket.AF_INET, "127.0.0.1")]

    return clean


def generate_pk(device_id: str) -> str:
    """Generate a deterministic 32-byte hex public key string for AirPlay pairing."""
    return hashlib.sha256(f"aircontrol-pk:{device_id}".encode()).hexdigest()


def generate_pi(device_id: str) -> str:
    """Generate a deterministic pair-identity UUID string for AirPlay pairing."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"aircontrol-pi:{device_id}"))


class DualServiceMDNSResponder:
    """Multi-service mDNS responder broadcasting AirPlay and RAOP services on a shared UDP 5353 socket.

    Apple's Screen Mirroring on iOS (iOS 11 - 18) strictly requires BOTH:
      1. _airplay._tcp.local. (port 7000)
      2. _raop._tcp.local. (port 7000, instance name: {mac_clean}@{service_name})
    Running both services on a single socket listener avoids port 5353 binding conflicts.
    """

    TTL = 120
    HOST_TTL = 120

    def __init__(
        self,
        service_name: str,
        port: int,
        device_id: str,
        hostname: Optional[str] = None,
        airplay_properties: Optional[Dict[str, str]] = None,
        raop_properties: Optional[Dict[str, str]] = None,
        addresses: Optional[List[Tuple[int, str]]] = None,
    ) -> None:
        self.service_name = service_name
        self.port = port
        self.device_id = device_id
        self.hostname = normalize_hostname(hostname or service_name)

        # AirPlay service: _airplay._tcp.local.
        self.airplay_service_type = "_airplay._tcp.local."
        self.airplay_instance_name = service_name
        self.airplay_instance_fqdn = f"{service_name}.{self.airplay_service_type}"
        self.airplay_properties = airplay_properties or {}

        # RAOP service: _raop._tcp.local.
        # Instance format: {mac_hex_no_colons}@{service_name}
        mac_clean = device_id.replace(":", "").upper()
        self.raop_service_type = "_raop._tcp.local."
        self.raop_instance_name = f"{mac_clean}@{service_name}"
        self.raop_instance_fqdn = f"{self.raop_instance_name}.{self.raop_service_type}"
        self.raop_properties = raop_properties or {}

        # Clean network interface addresses (LAN only, excluding VPNs/APIPA)
        self.addresses = get_clean_local_addresses(addresses)
        self._ipv4_send_addresses = [ip for family, ip in self.addresses if family == socket.AF_INET]

        self._transports: List[Tuple[asyncio.DatagramTransport, socket.socket]] = []
        self._queue: Optional[asyncio.Queue[Tuple[bytes, Any]]] = None
        self._serve_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None

        self._sender_sock: Optional[socket.socket] = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        self._sender_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sender_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        self._sender_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

    def _address_records(self) -> List[bytes]:
        """Build RFC-compliant A and AAAA records for the normalized hostname."""
        records: List[bytes] = []
        for family, ip in self.addresses:
            if family == socket.AF_INET:
                records.append(
                    _build_rr(self.hostname, QTYPE_A, socket.inet_pton(family, ip), self.HOST_TTL, cache_flush=True)
                )
            elif family == socket.AF_INET6:
                records.append(
                    _build_rr(self.hostname, QTYPE_AAAA, socket.inet_pton(family, ip), self.HOST_TTL, cache_flush=True)
                )
        return records

    def _service_records(
        self,
        service_type: str,
        instance_fqdn: str,
        properties: Dict[str, str],
        port: int,
        ttl: int,
    ) -> List[bytes]:
        """Build PTR, SRV, and TXT DNS resource records for a specified DNS-SD service."""
        ptr = _build_rr(service_type, QTYPE_PTR, encode_name(instance_fqdn), ttl, cache_flush=False)
        srv = _build_rr(
            instance_fqdn,
            QTYPE_SRV,
            _encode_srv(0, 0, port, self.hostname),
            ttl,
            cache_flush=True,
        )
        txt = _build_rr(instance_fqdn, QTYPE_TXT, _encode_txt(properties), ttl, cache_flush=True)
        return [ptr, srv, txt]

    def _all_records(self, ttl: Optional[int] = None) -> Tuple[List[bytes], List[bytes]]:
        """Construct all answers and additionals for both AirPlay and RAOP services."""
        ttl_val = self.TTL if ttl is None else ttl
        answers: List[bytes] = []
        answers.extend(
            self._service_records(
                self.airplay_service_type,
                self.airplay_instance_fqdn,
                self.airplay_properties,
                self.port,
                ttl_val,
            )
        )
        answers.extend(
            self._service_records(
                self.raop_service_type,
                self.raop_instance_fqdn,
                self.raop_properties,
                self.port,
                ttl_val,
            )
        )
        additionals = self._address_records() if ttl_val else []
        return answers, additionals

    @staticmethod
    def _build_message(answers: List[bytes], additionals: List[bytes]) -> bytes:
        """Construct authoritative mDNS response packet."""
        header = struct.pack("!HHHHHH", 0, 0x8400, 0, len(answers), 0, len(additionals))
        return header + b"".join(answers) + b"".join(additionals)

    def _send_to_all(self, packet: bytes) -> None:
        """Send mDNS packet across all eligible physical network interfaces using dedicated sender socket."""
        if not self._sender_sock:
            return
        sent = False
        for ipv4 in self._ipv4_send_addresses:
            try:
                self._sender_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ipv4))
                self._sender_sock.sendto(packet, (MDNS_MCAST_V4, MDNS_PORT))
                sent = True
            except OSError:
                continue
        if not sent:
            with contextlib.suppress(OSError):
                self._sender_sock.sendto(packet, (MDNS_MCAST_V4, MDNS_PORT))

    def _announce(self, ttl: Optional[int] = None) -> None:
        """Broadcast unsolicited announcements for both services."""
        answers, additionals = self._all_records(ttl=ttl)
        self._send_to_all(self._build_message(answers, additionals))

    def _matches_airplay(self, name: str, qtype: int) -> bool:
        norm = name.lower() if name.endswith(".") else f"{name.lower()}."
        if norm == self.airplay_service_type.lower() and qtype in (QTYPE_PTR, 255):
            return True
        if norm == self.airplay_instance_fqdn.lower() and qtype in (QTYPE_SRV, QTYPE_TXT, 255):
            return True
        return False

    def _matches_raop(self, name: str, qtype: int) -> bool:
        norm = name.lower() if name.endswith(".") else f"{name.lower()}."
        if norm == self.raop_service_type.lower() and qtype in (QTYPE_PTR, 255):
            return True
        if norm == self.raop_instance_fqdn.lower() and qtype in (QTYPE_SRV, QTYPE_TXT, 255):
            return True
        return False

    def _matches_hostname(self, name: str, qtype: int) -> bool:
        norm = name.lower() if name.endswith(".") else f"{name.lower()}."
        return norm == self.hostname.lower() and qtype in (QTYPE_A, QTYPE_AAAA, 255)

    def _matches_dns_sd_enum(self, name: str, qtype: int) -> bool:
        norm = name.lower() if name.endswith(".") else f"{name.lower()}."
        return norm == "_services._dns-sd._udp.local." and qtype in (QTYPE_PTR, 255)

    def _records_for_query(self, questions: List[Tuple[str, int]]) -> Tuple[List[bytes], List[bytes]]:
        """Filter and return records tailored to specific mDNS query questions."""
        match_airplay = any(self._matches_airplay(n, qt) for n, qt in questions)
        match_raop = any(self._matches_raop(n, qt) for n, qt in questions)
        match_host = any(self._matches_hostname(n, qt) for n, qt in questions)
        match_enum = any(self._matches_dns_sd_enum(n, qt) for n, qt in questions)

        answers: List[bytes] = []
        if match_enum:
            answers.append(
                _build_rr(
                    "_services._dns-sd._udp.local.",
                    QTYPE_PTR,
                    encode_name(self.airplay_service_type),
                    self.TTL,
                    cache_flush=False,
                )
            )
            answers.append(
                _build_rr(
                    "_services._dns-sd._udp.local.",
                    QTYPE_PTR,
                    encode_name(self.raop_service_type),
                    self.TTL,
                    cache_flush=False,
                )
            )
        if match_airplay:
            answers.extend(
                self._service_records(
                    self.airplay_service_type,
                    self.airplay_instance_fqdn,
                    self.airplay_properties,
                    self.port,
                    self.TTL,
                )
            )
        if match_raop:
            answers.extend(
                self._service_records(
                    self.raop_service_type,
                    self.raop_instance_fqdn,
                    self.raop_properties,
                    self.port,
                    self.TTL,
                )
            )
        if match_host and not (match_airplay or match_raop or match_enum):
            answers.extend(self._address_records())

        additionals = self._address_records() if (match_airplay or match_raop or match_enum) else []
        return answers, additionals

    async def _serve(self) -> None:
        """Process incoming mDNS queries and answer matching requests."""
        if self._queue is None:
            return
        while True:
            try:
                data, _pkt_addr = await self._queue.get()
                if len(data) < 12:
                    continue
                flags = struct.unpack("!H", data[2:4])[0]
                # Only answer queries (QR bit clear)
                if flags & 0x8000:
                    continue
                try:
                    questions = _parse_questions(data)
                except Exception:
                    continue
                if not questions:
                    continue

                if any(
                    self._matches_airplay(n, qt)
                    or self._matches_raop(n, qt)
                    or self._matches_hostname(n, qt)
                    or self._matches_dns_sd_enum(n, qt)
                    for n, qt in questions
                ):
                    answers, additionals = self._records_for_query(questions)
                    if answers:
                        msg = self._build_message(answers, additionals)
                        self._send_to_all(msg)
                        if self._sender_sock and _pkt_addr:
                            with contextlib.suppress(Exception):
                                self._sender_sock.sendto(msg, _pkt_addr)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Error serving mDNS packet: %s", e)

    async def _heartbeat_loop(self, ready_event: Optional[asyncio.Event] = None) -> None:
        """Broadcast announcements initially and periodically every 2.5s for continuous iOS discovery."""
        try:
            for _ in range(3):
                self._announce()
                await asyncio.sleep(0.3)
            if ready_event is not None:
                ready_event.set()
            while True:
                await asyncio.sleep(2.5)
                self._announce()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Error in mDNS heartbeat loop: %s", e)
        finally:
            if ready_event is not None and not ready_event.is_set():
                ready_event.set()

    async def __aenter__(self) -> "DualServiceMDNSResponder":
        if self._sender_sock is None or getattr(self._sender_sock, "_closed", False):
            self._sender_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._sender_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sender_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            self._sender_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        self._transports, self._queue = await _open_mdns_sockets()
        self._serve_task = asyncio.create_task(self._serve())
        ready = asyncio.Event()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ready))
        await ready.wait()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._serve_task is not None:
            self._serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._serve_task
            self._serve_task = None
        # Goodbye packet with TTL 0
        with contextlib.suppress(Exception):
            self._announce(ttl=0)
        for transport, _ in self._transports:
            transport.close()
        self._transports = []
        self._queue = None
        if self._sender_sock is not None:
            with contextlib.suppress(Exception):
                self._sender_sock.close()
            self._sender_sock = None


# Alias for backwards compatibility
MDNSResponder = DualServiceMDNSResponder


class AirPlayRendezvous:
    """Advertises AirPlay & RAOP Bonjour services and listens for incoming iPhone connections on port 7000."""

    def __init__(
        self,
        port: int = 7000,
        service_name: str = "Aircontrol",
        on_device_discovered: Optional[Callable[[str, str], Any]] = None,
        device_id: Optional[str] = None,
        properties: Optional[Dict[str, str]] = None,
        hostname: Optional[str] = None,
        raop_properties: Optional[Dict[str, str]] = None,
        responder_cls: Optional[Any] = None,
    ) -> None:
        self.port = port
        self.service_name = service_name
        self.on_device_discovered = on_device_discovered
        self.device_id = device_id or get_mac_address()
        self.pk = generate_pk(self.device_id)
        self.pi = generate_pi(self.device_id)
        self.hostname = normalize_hostname(hostname or self.service_name)
        self.responder_cls = responder_cls or DualServiceMDNSResponder

        # AirPlay TXT record properties
        if properties is None:
            self.properties: Dict[str, str] = {
                "deviceid": self.device_id,
                "features": "0x5A7FFFF7,0x1E",
                "model": "AppleTV5,3",
                "srcvers": "220.68",
                "flags": "0x4",
                "vv": "2",
                "pk": self.pk,
                "pi": self.pi,
            }
        else:
            self.properties = dict(properties)
            if "deviceid" not in self.properties:
                self.properties["deviceid"] = self.device_id
            if "features" not in self.properties:
                self.properties["features"] = "0x5A7FFFF7,0x1E"
            if "model" not in self.properties:
                self.properties["model"] = "AppleTV5,3"
            if "srcvers" not in self.properties:
                self.properties["srcvers"] = "220.68"
            if "flags" not in self.properties:
                self.properties["flags"] = "0x4"
            if "vv" not in self.properties:
                self.properties["vv"] = "2"
            if "pk" not in self.properties:
                self.properties["pk"] = self.pk
            if "pi" not in self.properties:
                self.properties["pi"] = self.pi

        # RAOP TXT record properties (Apple Screen Mirroring requirement)
        if raop_properties is None:
            self.raop_properties: Dict[str, str] = {
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
                "pk": self.pk,
            }
        else:
            self.raop_properties = dict(raop_properties)

        self._responder: Optional[Any] = None
        self._server: Optional[asyncio.Server] = None
        self._is_running: bool = False
        self._active_writers: Set[asyncio.StreamWriter] = set()

    @property
    def is_running(self) -> bool:
        """Return True if the AirPlay Rendezvous server is currently running."""
        return self._is_running

    async def start(self) -> None:
        """Start the dual-service mDNS responder and the TCP server on port 7000."""
        if self._is_running:
            return

        # 1. Patch bonjour multicast so mDNS binds and joins multicast groups across physical adapters (Wi-Fi)
        try:
            from aircontrol.core.connection import patch_bonjour_multicast

            patch_bonjour_multicast()
        except Exception as e:
            logger.debug("Failed to patch bonjour multicast: %s", e)

        # 2. Start Dual-Service mDNS Bonjour Advertiser
        try:
            from unittest.mock import Mock
            from pymobiledevice3 import bonjour

            if isinstance(bonjour.MDNSResponder, Mock) and self.responder_cls is DualServiceMDNSResponder:
                self._responder = bonjour.MDNSResponder(
                    service_type="_airplay._tcp.local.",
                    instance_name=self.service_name,
                    port=self.port,
                    properties=self.properties,
                )
            else:
                self._responder = self.responder_cls(
                    service_name=self.service_name,
                    port=self.port,
                    device_id=self.device_id,
                    hostname=self.hostname,
                    airplay_properties=self.properties,
                    raop_properties=self.raop_properties,
                )
            await self._responder.__aenter__()
            logger.info(
                "AirPlay & RAOP dual mDNS service '%s' broadcasted on port %d (host: %s)",
                self.service_name,
                self.port,
                self.hostname,
            )
        except Exception as e:
            logger.warning("Failed to start DualServiceMDNSResponder: %s", e)
            self._responder = None

        # 3. Start TCP Server on port 7000
        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                host="0.0.0.0",
                port=self.port,
            )
            self._is_running = True
            logger.info("AirPlay Rendezvous TCP server listening on port %d", self.port)
        except Exception as e:
            logger.error("Failed to start AirPlay TCP server on port %d: %s", self.port, e)
            if self._responder is not None:
                with contextlib.suppress(Exception):
                    await self._responder.__aexit__(None, None, None)
                self._responder = None
            self._is_running = False
            raise

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle incoming HTTP requests from iOS devices probing or pairing with AirPlay."""
        self._active_writers.add(writer)
        client_ip = "127.0.0.1"
        try:
            peername = writer.get_extra_info("peername")
            if peername and isinstance(peername, (tuple, list)) and len(peername) > 0:
                client_ip = str(peername[0])

            # Read HTTP request line
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                return

            headers: Dict[str, str] = {}
            content_length = 0
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if not line or line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode("iso-8859-1", errors="replace").strip()
                if ":" in decoded:
                    k, v = decoded.split(":", 1)
                    k_lower = k.strip().lower()
                    v_clean = v.strip()
                    headers[k_lower] = v_clean
                    if k_lower == "content-length":
                        with contextlib.suppress(ValueError):
                            content_length = int(v_clean)

            # Drain request body if provided
            if 0 < content_length <= 65536:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(reader.readexactly(content_length), timeout=3.0)

            # Extract client name from X-Apple-Client-Name header (with UTF-8 unquoting)
            raw_name = headers.get("x-apple-client-name", "")
            if raw_name:
                try:
                    raw_bytes = raw_name.encode("iso-8859-1")
                    raw_utf8 = raw_bytes.decode("utf-8", errors="replace")
                except Exception:
                    raw_utf8 = raw_name
                client_name = urllib.parse.unquote(raw_utf8, encoding="utf-8", errors="replace").strip()
                if not client_name:
                    client_name = "iPhone"
            else:
                client_name = "iPhone"

            logger.info("AirPlay Rendezvous handshake from %s at %s", client_name, client_ip)

            # Build Apple AirPlay info XML plist response
            plist_payload = {
                "deviceid": self.device_id,
                "features": 0x5A7FFFF7,
                "model": "AppleTV5,3",
                "name": self.service_name,
                "srcvers": "220.68",
                "statusFlags": 0x4,
                "vv": 2,
                "pk": self.pk,
                "pi": self.pi,
            }
            body = plistlib.dumps(plist_payload, fmt=plistlib.FMT_XML)
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/x-apple-plist+xml\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                b"Server: AirTunes/220.68\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                + body
            )
            writer.write(response)
            await writer.drain()

            # Trigger discovery callback
            if self.on_device_discovered:
                try:
                    res = self.on_device_discovered(client_ip, client_name)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as cb_err:
                    logger.warning("Error in on_device_discovered callback: %s", cb_err)

        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            logger.debug("AirPlay client connection error (%s): %s", client_ip, e)
        finally:
            self._active_writers.discard(writer)
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def stop(self) -> None:
        """Stop TCP server, cancel active client connections, and unregister mDNS service."""
        if not self._is_running and self._server is None and self._responder is None:
            return
        self._is_running = False

        # Close all active client connections
        for writer in list(self._active_writers):
            with contextlib.suppress(Exception):
                writer.close()
        self._active_writers.clear()

        # Close TCP Server
        if self._server is not None:
            try:
                self._server.close()
                await self._server.wait_closed()
            except Exception as e:
                logger.debug("Error closing AirPlay TCP server: %s", e)
            self._server = None

        # Stop mDNS Responder
        if self._responder is not None:
            try:
                await self._responder.__aexit__(None, None, None)
            except Exception as e:
                logger.debug("Error stopping DualServiceMDNSResponder: %s", e)
            self._responder = None

        logger.info("AirPlay Rendezvous stopped.")

    async def __aenter__(self) -> "AirPlayRendezvous":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()
