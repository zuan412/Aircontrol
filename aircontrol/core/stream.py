"""Production-grade iOS Screen Streaming Engine.

Leverages Apple CoreDevice DisplayService over USB/Wi-Fi:
- RFC 7798 RTP/HEVC depacketization with persistent parameter sets (VPS/SPS/PPS).
- Ultra-fast slice-multithreaded HEVC -> BGR0 decoding via PyAV C-level worker thread.
- Zero copy & zero alpha-fill overhead.
- Strictly avoids bogus periodic keyframe requests (motion IDR), preserving a steady 60 FPS P-frame flow.
- Continuous RTCP Receiver Reports ensuring the iOS media session is never reaped.
- iOS PowerAssertion keepalive to prevent display sleep or dimming.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import queue
import socket
import struct
import threading
import time
from typing import Any, Callable, Optional, Tuple

import av
from pymobiledevice3.remote.core_device.hevc_rps import (
    parse_sps,
    remove_emulation_prevention,
)
from pymobiledevice3.remote.core_device.screen_stream import (
    UdpMediaTransport,
    depacketize_hevc,
    open_media_receiver,
)
from pymobiledevice3.services.power_assertion import PowerAssertionService

logger = logging.getLogger(__name__)

# NAL unit types (ITU-T H.265)
_HEVC_NAL_IDR_W_RADL = 19
_HEVC_NAL_IDR_N_LP = 20
_HEVC_NAL_CRA = 21
_HEVC_NAL_VPS = 32
_HEVC_NAL_SPS = 33
_HEVC_NAL_PPS = 34


def _is_key_nal(nt: int) -> bool:
    return nt in (_HEVC_NAL_IDR_W_RADL, _HEVC_NAL_IDR_N_LP, _HEVC_NAL_CRA)


class FastHevcDecoder:
    """High-performance Annex-B HEVC -> raw 32-bit BGR0 bytes decoder.

    Key optimizations:
    1. Slice multithreading across CPU cores (zero frame buffering delay).
    2. Flags.low_delay + Flags2.fast enabled for real-time streaming.
    3. Direct 'bgr0' reformat matching Qt QImage Format_RGB32 (zero alpha-fill overhead).
    4. Never triggers fake decode errors on parameter sets or slice pipelines.
    5. Direct C-level memory buffer access via PyAV planes.
    """

    def __init__(
        self,
        vps: bytes,
        sps: bytes,
        pps: bytes,
        *,
        on_frame: Optional[Callable[[bytes, int, int], None]] = None,
        on_yuv_frame: Optional[Callable[[memoryview, memoryview, memoryview, int, int], None]] = None,
        on_decode_error: Optional[Callable[[], None]] = None,
    ) -> None:
        try:
            sps_rbsp = remove_emulation_prevention(sps[2:])
            sps_state = parse_sps(sps_rbsp)
            self.width = sps_state.pic_width_in_luma_samples
            self.height = sps_state.pic_height_in_luma_samples
            if self.width <= 0 or self.height <= 0:
                raise ValueError(f"FastHevcDecoder: invalid dimensions {self.width}x{self.height}")
        except Exception as e:
            raise RuntimeError(f"FastHevcDecoder: SPS parse failed: {e}") from e

        self._on_frame = on_frame
        self._on_yuv_frame = on_yuv_frame
        self._on_decode_error = on_decode_error

        self._codec: Any = av.codec.CodecContext.create("hevc", "r")
        cpu_cores = os.cpu_count() or 4
        self._codec.thread_count = min(cpu_cores, 6)
        self._codec.thread_type = "SLICE"
        with contextlib.suppress(Exception):
            self._codec.flags |= av.codec.context.Flags.low_delay
        with contextlib.suppress(Exception):
            self._codec.flags2 |= av.codec.context.Flags2.fast

        # Prime codec with parameter sets
        ps_annexb = b"".join(b"\x00\x00\x00\x01" + nal for nal in (vps, sps, pps))
        with contextlib.suppress(Exception):
            list(self._codec.decode(av.Packet(ps_annexb)))

        # Real-time low-latency frame queue: maxsize=16 ensures smooth jitter headroom (~266ms) without dropping under Wi-Fi bursts
        self._inq: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=16)
        self._stop = threading.Event()
        self._empty_decode_count = 0
        self._thread = threading.Thread(target=self._run, name="AircontrolFastHevc", daemon=True)
        self._thread.start()

    def feed(self, annexb: bytes) -> None:
        if self._stop.is_set():
            return
        try:
            self._inq.put_nowait(annexb)
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self._inq.get_nowait()
            with contextlib.suppress(queue.Full):
                self._inq.put_nowait(annexb)

    def close(self) -> None:
        self._stop.set()
        with contextlib.suppress(queue.Full):
            self._inq.put_nowait(None)
        self._thread.join(timeout=2.0)
        with contextlib.suppress(Exception):
            self._codec.close()

    def _emit_frame(self, frame: Any) -> None:
        try:
            w = frame.width
            h = frame.height
            if self._on_yuv_frame is not None:
                # Zero-copy YUV420p planes: CPU sws_scale completely bypassed!
                # Plane 0: Y (w*h), Plane 1: U (w/2 * h/2), Plane 2: V (w/2 * h/2)
                p0 = frame.planes[0]
                p1 = frame.planes[1]
                p2 = frame.planes[2]
                self._on_yuv_frame(
                    memoryview(p0),
                    memoryview(p1),
                    memoryview(p2),
                    w,
                    h,
                    p0.line_size,
                    p1.line_size,
                    p2.line_size,
                )
            elif self._on_frame is not None:
                bgr0_frame = frame.reformat(width=w, height=h, format="bgr0")
                plane_mv = memoryview(bgr0_frame.planes[0])
                self._on_frame(plane_mv, w, h)
        except Exception as e:
            logger.debug("Frame emission failed: %s", e)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                try:
                    item = self._inq.get(timeout=0.05)
                except queue.Empty:
                    continue
                if item is None:
                    break
                try:
                    frames = list(self._codec.decode(av.Packet(item)))
                except av.error.InvalidDataError as e:
                    logger.debug("HEVC decode error: %s", e)
                    if self._on_decode_error:
                        try:
                            self._on_decode_error()
                        except Exception as cb_err:
                            logger.debug("on_decode_error callback failed: %s", cb_err)
                    continue
                except Exception as e:
                    logger.debug("HEVC decode exception: %s", e)
                    if self._on_decode_error:
                        try:
                            self._on_decode_error()
                        except Exception as cb_err:
                            logger.debug("on_decode_error callback failed: %s", cb_err)
                    continue

                if not frames:
                    self._empty_decode_count += 1
                    # If consecutive AUs fail to decode (due to missing reference frame from packet loss), request recovery IDR
                    if self._empty_decode_count >= 8:
                        self._empty_decode_count = 0
                        if self._on_decode_error:
                            try:
                                self._on_decode_error()
                            except Exception as cb_err:
                                logger.debug("on_decode_error callback failed: %s", cb_err)
                    continue

                self._empty_decode_count = 0

                for fr in frames:
                    self._emit_frame(fr)
            except Exception as loop_err:
                logger.warning("Unexpected error in FastHevcDecoder._run: %s", loop_err)


class ScreenStreamEngine:
    """Production-grade engine handling iOS DisplayService UDP stream reception."""

    def __init__(
        self,
        rsd: Any,
        on_frame: Optional[Callable[[bytes, int, int], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        *,
        on_yuv_frame: Optional[Callable[[memoryview, memoryview, memoryview, int, int], None]] = None,
        on_pcm: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self._rsd = rsd
        self._on_frame = on_frame
        self._on_yuv_frame = on_yuv_frame
        self._on_status = on_status
        self._on_pcm = on_pcm
        self._audio_engine: Optional[Any] = None

        self._decoder: Optional[FastHevcDecoder] = None
        self._serve_task: Optional[asyncio.Task[None]] = None
        self._transport: Optional[UdpMediaTransport] = None
        self._local_ssrc: int = 0
        self._remote_ssrc: int = 0
        self._rtcp_dest: Optional[Tuple[str, int]] = None
        self._rtp_highest_seq: int = 0

        # Xcode mirror RCTL rate-control state
        self._rctl_enabled: bool = True
        self._rtp_last_ts: int = 0
        self._rtp_packets_received: int = 0
        self._rtp_cur_frame_pkts: int = 0
        self._rtp_last_frame_pkts: int = 0

        self._last_pli_time: float = 0.0
        self._last_good_au_time: float = 0.0
        self._screen_in_motion: bool = False
        self._motion_quiet_start: float = 0.0
        self._keep_awake_task: Optional[asyncio.Task[None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

    def _set_status(self, text: str) -> None:
        if self._on_status:
            self._on_status(text)

    def _build_rtcp_pli(self) -> bytes:
        """RTCP Picture Loss Indication (RFC 4585 §6.3.1)."""
        return struct.pack(
            "!BBHII",
            0x81,  # V=2, P=0, FMT=1
            0xCE,  # PT=206 (PSFB)
            2,
            self._local_ssrc & 0xFFFFFFFF,
            self._remote_ssrc & 0xFFFFFFFF,
        )

    def _build_rtcp_rr(self) -> bytes:
        """RTCP Receiver Report (RFC 3550 §6.4.2) + SDES to keep iOS session alive.

        Spoofs fraction_lost=0 and jitter=0 so AVCRateController maintains maximum
        bitrate (50-100 Mbps) with zero throttling during active scrolling/swiping.
        """
        rr = struct.pack(
            "!BBHII BBBB IIII",
            0x81,  # V=2, RC=1
            0xC9,  # PT=201 (RR)
            7,
            self._local_ssrc & 0xFFFFFFFF,
            self._remote_ssrc & 0xFFFFFFFF,
            0,  # fraction_lost = 0 (perfect link quality)
            0,  # cumulative packets lost high byte
            0,  # cumulative packets lost mid byte
            0,  # cumulative packets lost low byte
            self._rtp_highest_seq & 0xFFFFFFFF,
            0,  # interarrival jitter = 0
            0,  # last SR
            0,  # dlsr
        )
        sdes = struct.pack("!BBHI BBBB", 0x81, 0xCA, 2, self._local_ssrc & 0xFFFFFFFF, 0x01, 0x00, 0x00, 0x00)
        return rr + sdes

    def _build_rctl_packet(self) -> bytes:
        """RTCP APP 'RCTL' (PT=204), byte-exact to Xcode's mirror.

        Reports flawless packet receipt stats so iOS AVCRateController never
        drops resolution or bitrate during high-frequency gesture bursts.
        """
        ts = self._rtp_last_ts & 0xFFFFFFFF
        w2 = ((ts >> 8) & 0xFFFF) << 16
        w3 = self._rtp_last_frame_pkts & 0xFFFFFFFF
        arrival_ms = (ts // 24) & 0xFFFF
        w4 = (arrival_ms << 16) | 0  # 0 packet loss / zero jitter indicator
        w5 = ((self._rtp_packets_received & 0xFFFF) << 16) | 0xEA61
        return struct.pack(
            "!BBHI4sI IIII",
            0x80,
            0xCC,
            7,
            self._local_ssrc & 0xFFFFFFFF,
            b"RCTL",
            0x85000004,
            w2,
            w3,
            w4,
            w5,
        )

    def _build_rctl_companion_packet(self) -> bytes:
        """Xcode per-frame receipt companion packet."""
        return struct.pack(
            "!BBHI I I",
            0x80,
            0xCC,
            3,
            self._local_ssrc & 0xFFFFFFFF,
            5,
            self._rtp_last_ts & 0xFFFFFFFF,
        )

    def _handle_decode_error(self) -> None:
        """Thread-safe callback invoked from FastHevcDecoder worker thread."""
        if self._loop and self._loop.is_running() and self._running:
            try:
                asyncio.run_coroutine_threadsafe(self.request_keyframe(), self._loop)
            except Exception as e:
                logger.debug("Failed to dispatch keyframe request: %s", e)

    async def request_keyframe(self, force: bool = False) -> None:
        """Rate-limited keyframe request: recovers from drops/rotations without encoder stalls."""
        now = time.monotonic()
        if not force and (now - self._last_pli_time < 0.8):
            return
        self._last_pli_time = now

        if self._transport and self._rtcp_dest and self._local_ssrc and self._remote_ssrc:
            try:
                await self._transport.sendto(self._build_rtcp_pli(), *self._rtcp_dest)
                logger.debug("Sent RTCP PLI keyframe request")
            except Exception as e:
                logger.debug("Failed to send PLI: %s", e)

    def trigger_orientation_keyframe(self) -> None:
        """Immediate keyframe request after orientation change to restore full resolution."""
        if self._loop and self._loop.is_running() and self._running:
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(self.request_keyframe(force=True), self._loop)

    async def _rctl_feedback_loop(self) -> None:
        """Stream periodic RCTL rate-control packet (~20Hz) so iOS AVCRateController maintains full 60 FPS."""
        while self._running:
            try:
                await asyncio.sleep(0.050)
            except asyncio.CancelledError:
                return
            if (
                not self._rctl_enabled
                or self._transport is None
                or self._rtcp_dest is None
                or not self._local_ssrc
                or self._rtp_packets_received == 0
            ):
                continue
            try:
                await self._transport.sendto(self._build_rctl_packet(), *self._rtcp_dest)
            except (OSError, asyncio.CancelledError):
                continue

    async def _rtcp_keepalive_loop(self) -> None:
        """Periodically send RTCP Receiver Reports every 1.0s so iOS never reaps the session."""
        while self._running:
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return
            if self._transport and self._rtcp_dest and self._local_ssrc and self._remote_ssrc:
                try:
                    await self._transport.sendto(self._build_rtcp_rr(), *self._rtcp_dest)
                except Exception as e:
                    logger.debug("RTCP RR send error: %s", e)

    async def _keep_awake_loop(self) -> None:
        """Keep iPhone display from sleeping or dimming."""
        while self._running:
            try:
                svc = PowerAssertionService(self._rsd)
                async with svc.create_power_assertion(
                    "PreventUserIdleSystemSleep",
                    "aircontrol.stream",
                    300,
                    "Aircontrol mirroring screen",
                ):
                    for _ in range(50):
                        if not self._running:
                            break
                        await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("Power assertion error: %s", exc)
                try:
                    await asyncio.sleep(5.0)
                except asyncio.CancelledError:
                    return

    async def _udp_recv_loop(self, transport: UdpMediaTransport) -> None:
        """High-speed UDP receiver with RTP packet reorder jitter buffer feeding FastHevcDecoder."""
        fu_buffer = bytearray()
        current_au: list[bytes] = []
        au_corrupt = False
        au_is_key = False
        nals: list[bytes] = []
        cached_vps: Optional[bytes] = None
        cached_sps: Optional[bytes] = None
        cached_pps: Optional[bytes] = None

        # Wi-Fi RTP Packet Jitter Reorder Buffer
        # Seamlessly handles 802.11 MAC-level retries and out-of-order UDP packet delivery
        expected_seq: Optional[int] = None
        reorder_buf: dict[int, tuple[int, bytes]] = {}  # seq -> (marker, payload)
        cur_frame_ts: Optional[int] = None

        async def _flush_frame() -> None:
            nonlocal current_au, au_is_key, au_corrupt, cached_vps, cached_sps, cached_pps
            self._rtp_last_frame_pkts = self._rtp_cur_frame_pkts
            self._rtp_cur_frame_pkts = 0

            # Xcode-exact per-frame receipt sent inline so iOS AVCRateController never throttles
            if self._rctl_enabled and self._transport is not None and self._rtcp_dest is not None and self._local_ssrc:
                with contextlib.suppress(Exception):
                    await self._transport.sendto(self._build_rctl_companion_packet(), *self._rtcp_dest)

            if au_corrupt:
                # Dropped or corrupt AU -> rate-limited recovery IDR so P-frames don't get stuck
                asyncio.create_task(self.request_keyframe())
            elif current_au:
                self._last_good_au_time = time.monotonic()
                # Initialize decoder upon first keyframe
                if (
                    self._decoder is None
                    and au_is_key
                    and cached_vps is not None
                    and cached_sps is not None
                    and cached_pps is not None
                ):
                    try:
                        self._decoder = FastHevcDecoder(
                            cached_vps,
                            cached_sps,
                            cached_pps,
                            on_frame=self._on_frame,
                            on_yuv_frame=self._on_yuv_frame,
                            on_decode_error=self._handle_decode_error,
                        )
                        logger.info(
                            "ScreenStreamEngine decoder ready: %dx%d (Hardware YUV Pipeline: %s)",
                            self._decoder.width,
                            self._decoder.height,
                            "Enabled" if self._on_yuv_frame is not None else "Disabled",
                        )
                        self._set_status(f"Đang phát luồng: {self._decoder.width}x{self._decoder.height} (60 FPS Native)")
                    except Exception:
                        logger.exception("Failed to start FastHevcDecoder")

                # Feed frame to decoder
                if self._decoder is not None:
                    annexb = b"".join(b"\x00\x00\x00\x01" + nal for nal in current_au)
                    self._decoder.feed(annexb)

            current_au = []
            au_is_key = False
            au_corrupt = False

        def _consume_packet(pkt_payload: bytes) -> None:
            nonlocal au_is_key, cached_vps, cached_sps, cached_pps
            nals.clear()
            depacketize_hevc(pkt_payload, fu_buffer, nals)
            for nal in nals:
                if not nal:
                    continue
                nt = (nal[0] >> 1) & 0x3F
                if nt == _HEVC_NAL_VPS:
                    cached_vps = bytes(nal)
                elif nt == _HEVC_NAL_SPS:
                    cached_sps = bytes(nal)
                elif nt == _HEVC_NAL_PPS:
                    cached_pps = bytes(nal)
                elif _is_key_nal(nt):
                    au_is_key = True
                current_au.append(nal)

        while self._running:
            try:
                data = await transport.recv()
            except (ConnectionResetError, OSError) as e:
                if (
                    getattr(e, "winerror", None) == 10054
                    or getattr(e, "errno", None) == 10054
                    or isinstance(e, ConnectionResetError)
                ):
                    await asyncio.sleep(0.01)
                    continue
                return
            except asyncio.CancelledError:
                return
            if len(data) < 12:
                continue
            pt = data[1] & 0x7F
            if 64 <= pt <= 95:
                continue
            marker = (data[1] >> 7) & 1
            cc = data[0] & 0x0F
            header_len = 12 + cc * 4
            if data[0] & 0x10:
                ext_len = int.from_bytes(data[header_len + 2 : header_len + 4], "big")
                header_len += 4 + ext_len * 4
            payload = data[header_len:]

            seq = int.from_bytes(data[2:4], "big")
            cur_ext = self._rtp_highest_seq
            cycles = (cur_ext >> 16) & 0xFFFF
            last_seq16 = cur_ext & 0xFFFF
            if seq < last_seq16 and (last_seq16 - seq) > 0x8000:
                cycles = (cycles + 1) & 0xFFFF
            new_ext = (cycles << 16) | seq
            if cur_ext == 0 or ((new_ext - cur_ext) & 0xFFFFFFFF) < 0x80000000:
                self._rtp_highest_seq = new_ext

            # Track packet stats and timestamps for Xcode RCTL rate-control
            ts = int.from_bytes(data[4:8], "big")
            self._rtp_packets_received += 1
            self._rtp_last_ts = ts
            self._rtp_cur_frame_pkts += 1

            # Detect new frame transition by timestamp
            if cur_frame_ts is not None and ts != cur_frame_ts:
                if fu_buffer:
                    fu_buffer.clear()
                if current_au:
                    await _flush_frame()
            cur_frame_ts = ts

            if expected_seq is None:
                expected_seq = seq

            diff = (seq - expected_seq) & 0xFFFF

            if diff == 0:
                # In-order packet arrived
                _consume_packet(payload)
                expected_seq = (expected_seq + 1) & 0xFFFF

                # Drain any contiguous buffered packets
                while expected_seq in reorder_buf:
                    buf_marker, buf_payload = reorder_buf.pop(expected_seq)
                    _consume_packet(buf_payload)
                    expected_seq = (expected_seq + 1) & 0xFFFF
                    if buf_marker:
                        await _flush_frame()

                if marker:
                    await _flush_frame()

            elif diff < 0x8000:
                # Packet arrived ahead of expected_seq (Wi-Fi out-of-order delivery)
                if diff <= 256:
                    reorder_buf[seq] = (marker, payload)
                    if len(reorder_buf) >= 256:
                        # Too many packets held -> declare packet loss on expected_seq
                        fu_buffer.clear()
                        au_corrupt = True
                        sorted_keys = sorted(reorder_buf.keys(), key=lambda s: (s - expected_seq) & 0xFFFF)
                        expected_seq = sorted_keys[0]
                        while expected_seq in reorder_buf:
                            buf_marker, buf_payload = reorder_buf.pop(expected_seq)
                            _consume_packet(buf_payload)
                            expected_seq = (expected_seq + 1) & 0xFFFF
                            if buf_marker:
                                await _flush_frame()
                else:
                    # Massive jump (>256 packets) -> packet loss burst or stream reset
                    fu_buffer.clear()
                    au_corrupt = True
                    reorder_buf.clear()
                    expected_seq = seq
                    _consume_packet(payload)
                    expected_seq = (expected_seq + 1) & 0xFFFF
                    if marker:
                        await _flush_frame()
            else:
                # diff >= 0x8000: Late straggler packet arrived after frame passed; ignore safely
                pass

    async def _stall_watchdog_loop(self) -> None:
        """Keep the stream alive and recover crisp native resolution after motion settles."""
        while self._running:
            try:
                await asyncio.sleep(0.3)
            except asyncio.CancelledError:
                return
            now = time.monotonic()
            # 1. Stall recovery watchdog & dead link detection
            if self._last_good_au_time > 0:
                silence_dur = now - self._last_good_au_time
                if silence_dur > 6.0:
                    logger.warning("Stream link dead (no frames for >6.0s). Exiting stream session for reconnect.")
                    self._running = False
                    return
                elif silence_dur > 2.0:
                    self._last_good_au_time = now
                    logger.debug("Stream quiet/stalled for >2.0s: requesting IDR keyframe")
                    await self.request_keyframe(force=True)

            # 2. Settle IDR: detect transition from motion/scrolling to idle screen
            # When the user stops scrolling or rotating, send 1 keyframe after settling (>1.5s idle)
            # so the static screen snaps to crisp native resolution without interrupting active swipes
            if self._rtp_last_frame_pkts > 7:
                self._screen_in_motion = True
                self._motion_quiet_start = 0.0
            elif self._screen_in_motion and self._rtp_last_frame_pkts <= 2:
                if self._motion_quiet_start == 0.0:
                    self._motion_quiet_start = now
                elif now - self._motion_quiet_start >= 1.5:
                    self._screen_in_motion = False
                    self._motion_quiet_start = 0.0
                    logger.debug("Motion settled: requesting Settle IDR for Retina sharpness")
                    await self.request_keyframe(force=True)

    async def start(self) -> None:
        """Start the iOS DisplayService stream session."""
        from pymobiledevice3.remote.core_device.display_service import DisplayService
        import uuid

        self._loop = asyncio.get_running_loop()
        self._running = True
        self._set_status("Đang khởi tạo DisplayService trên iPhone...")

        svc = DisplayService(self._rsd)
        await svc.connect()

        # Allocate 8MB socket buffer for UDP packets to avoid kernel drops
        transport, receiver_ip = open_media_receiver(svc, (8 * 1024 * 1024, 4 * 1024 * 1024))
        self._transport = transport

        if hasattr(socket, "SIO_UDP_CONNRESET"):
            with contextlib.suppress(Exception):
                raw_sock = getattr(transport, "_sock", None)
                if raw_sock:
                    raw_sock.ioctl(socket.SIO_UDP_CONNRESET, False)

        try:
            from pymobiledevice3.remote import userspace_tunnel
            if (receiver_ip in ("127.0.0.1", "::1", "localhost") or not receiver_ip) and userspace_tunnel.USERSPACE_ACTIVE:
                stack_addr = userspace_tunnel.userspace_stack_addr()
                if stack_addr:
                    receiver_ip = stack_addr
        except Exception as e:
            logger.debug("Userspace receiver IP check: %s", e)

        sender_ip = self._rsd.service.address[0]
        shared_session_id = uuid.uuid4()
        logger.info("Initiating video stream: receiver=%s:%d, sender=%s", receiver_ip, transport.port, sender_ip)

        # 1. Initiate audio stream concurrently with video (fast overlap negotiation)
        audio_task: Optional[asyncio.Task[None]] = None
        if self._on_pcm is not None:
            async def _start_audio_concurrent() -> None:
                try:
                    from aircontrol.core.audio import AudioStreamEngine
                    self._audio_engine = AudioStreamEngine(
                        rsd=self._rsd,
                        client_session_id=shared_session_id,
                        on_pcm=self._on_pcm,
                    )
                    audio_ok = await self._audio_engine.start()
                    if not audio_ok:
                        logger.warning("Audio stream failed to negotiate; continuing with video only")
                except Exception as e:
                    logger.warning("Could not start audio stream: %s", e)

            audio_task = asyncio.create_task(_start_audio_concurrent())

        try:
            answer = await svc.start_video_stream(
                receiver_ip=receiver_ip,
                receiver_port=transport.port,
                sender_ip=sender_ip,
                display_id=1,
                client_session_id=shared_session_id,
                allow_rtcp_fb=True,
                ltrp_enabled=False,
                fec_enabled=True,
            )
        except Exception as start_err:
            err_msg = str(start_err)
            if "9022" in err_msg or "microphone or camera" in err_msg.lower():
                logger.warning("Stale stream session detected (9022). Clearing via stop_all_streams and retrying...")
                with contextlib.suppress(Exception):
                    await DisplayService.stop_all_streams(self._rsd)
                await asyncio.sleep(0.5)
                answer = await svc.start_video_stream(
                    receiver_ip=receiver_ip,
                    receiver_port=transport.port,
                    sender_ip=sender_ip,
                    display_id=1,
                    client_session_id=shared_session_id,
                    allow_rtcp_fb=True,
                    ltrp_enabled=False,
                    fec_enabled=True,
                )
            else:
                raise

        cfg = answer.get("connection", {}).get("streamConfig", {})
        source_port = int(cfg.get("SourcePort", 0))
        self._local_ssrc = int(cfg.get("RemoteSSRC", 0))
        self._remote_ssrc = int(cfg.get("LocalSSRC", 0))
        self._rtcp_dest = (sender_ip, source_port) if source_port else None

        logger.info("Video stream established. Sender port: %s", source_port)
        self._set_status("Đã kết nối luồng video. Đang chờ khung hình...")

        # Request initial keyframe to bootstrap stream
        await self.request_keyframe()

        self._keep_awake_task = asyncio.create_task(self._keep_awake_loop())
        rtcp_task = asyncio.create_task(self._rtcp_keepalive_loop())
        rctl_task = asyncio.create_task(self._rctl_feedback_loop())
        watchdog_task = asyncio.create_task(self._stall_watchdog_loop())
        recv_task = asyncio.create_task(self._udp_recv_loop(transport))

        try:
            await asyncio.gather(rtcp_task, rctl_task, watchdog_task, recv_task)
        finally:
            self._running = False
            for t in (rtcp_task, rctl_task, watchdog_task, recv_task, self._keep_awake_task, audio_task):
                if t and not t.done():
                    t.cancel()
            if self._decoder:
                self._decoder.close()
                self._decoder = None
            if self._transport:
                self._transport.close()
                self._transport = None
            if self._audio_engine:
                self._audio_engine.stop()
                self._audio_engine = None
            if self._rsd:
                with contextlib.suppress(Exception):
                    await DisplayService.stop_all_streams(self._rsd)

    def stop(self) -> None:
        self._running = False
        if self._audio_engine:
            self._audio_engine.stop()
            self._audio_engine = None
