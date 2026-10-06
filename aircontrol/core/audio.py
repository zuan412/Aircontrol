"""Production-grade iOS System Audio Streaming Engine.

Leverages Apple CoreDevice DisplayService audio endpoint over USB/Wi-Fi:
- Streams system audio (PT=101) directly from iOS.
- Decodes AAC-ELD (AOT 39, 48 kHz stereo, 480 samples/frame) to signed 16-bit PCM.
- Continuous RTCP Receiver Reports ensuring iOS never reaps the audio session.
- Thread-safe non-blocking PCM dispatch for local speaker output.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import struct
from typing import Any, Callable, Optional, Tuple
import uuid

import ctypes
import os
import sys
import av
from pymobiledevice3.remote.core_device.display_service import DisplayService
from pymobiledevice3.remote.core_device.screen_stream import (
    UdpMediaTransport,
    open_media_receiver,
)

logger = logging.getLogger(__name__)

# Standard AudioSpecificConfig for AAC-ELD @ 48 kHz stereo, 480 samples/frame.
# 0xF8, 0xE6, 0x40, 0x00 is the exact 4-byte cookie captured from Apple CoreDevice Mirror audio handshake.
AAC_ELD_ASC_48K_STEREO_480: bytes = bytes([0xF8, 0xE6, 0x40, 0x00])


class CStreamInfo(ctypes.Structure):
    """Fraunhofer FDK AAC decoder stream info structure."""

    _fields_ = [
        ("sampleRate", ctypes.c_int32),
        ("frameSize", ctypes.c_int32),
        ("numChannels", ctypes.c_int32),
        ("pChannelType", ctypes.c_void_p),
        ("pChannelIndices", ctypes.c_void_p),
        ("aacSampleRate", ctypes.c_int32),
        ("profile", ctypes.c_int32),
        ("aot", ctypes.c_int32),
        ("channelConfig", ctypes.c_int32),
        ("bitRate", ctypes.c_int32),
        ("aacSamplesPerFrame", ctypes.c_int32),
        ("extPosition", ctypes.c_int32),
        ("outputDelay", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
    ]


class FdkAacEldDecoder:
    """High-performance native AAC-ELD decoder using Fraunhofer FDK AAC (libfdk-aac-2.dll).

    Handles Apple CoreDevice DisplayService audio stream:
    - Transport format: TT_MP4_RAW (0)
    - Magic Cookie: AudioSpecificConfig (AAC_ELD_ASC_48K_STEREO_480)
    - Output: interleaved signed 16-bit stereo PCM (1920 bytes per 10ms frame @ 48 kHz).
    """

    def __init__(self, magic_cookie: bytes = AAC_ELD_ASC_48K_STEREO_480, dll_path: Optional[str] = None) -> None:
        if dll_path is None:
            candidates = []
            if getattr(sys, "frozen", False):
                if hasattr(sys, "_MEIPASS"):
                    candidates.append(os.path.join(sys._MEIPASS, "aircontrol", "bin", "libfdk-aac-2.dll"))
                    candidates.append(os.path.join(sys._MEIPASS, "bin", "libfdk-aac-2.dll"))
                    candidates.append(os.path.join(sys._MEIPASS, "libfdk-aac-2.dll"))
                exe_dir = os.path.dirname(sys.executable)
                candidates.append(os.path.join(exe_dir, "bin", "libfdk-aac-2.dll"))
                candidates.append(os.path.join(exe_dir, "libfdk-aac-2.dll"))

            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates.append(os.path.join(base_dir, "bin", "libfdk-aac-2.dll"))

            for c in candidates:
                if os.path.isfile(c):
                    dll_path = c
                    break
            else:
                dll_path = candidates[0] if candidates else ""

        if not os.path.isfile(dll_path):
            raise FileNotFoundError(f"FDK AAC DLL not found at: {dll_path}")

        self._lib = ctypes.CDLL(dll_path)
        self._init_api()

        self._handle = self._lib.aacDecoder_Open(0, 1)  # TT_MP4_RAW = 0, nrOfLayers = 1
        if not self._handle:
            raise RuntimeError("aacDecoder_Open failed to allocate decoder handle")

        asc_buf = (ctypes.c_uint8 * len(magic_cookie)).from_buffer_copy(magic_cookie)
        asc_ptr = ctypes.cast(asc_buf, ctypes.POINTER(ctypes.c_uint8))
        asc_ptrs = (ctypes.POINTER(ctypes.c_uint8) * 1)(asc_ptr)
        asc_sizes = (ctypes.c_uint32 * 1)(len(magic_cookie))
        err = self._lib.aacDecoder_ConfigRaw(self._handle, asc_ptrs, asc_sizes)
        if err != 0 and magic_cookie == AAC_ELD_ASC_48K_STEREO_480:
            # Fallback to alternate framing flag 0x50 if 0x40 is rejected
            fallback = bytes([0xF8, 0xE6, 0x50, 0x00])
            asc_buf = (ctypes.c_uint8 * len(fallback)).from_buffer_copy(fallback)
            asc_ptr = ctypes.cast(asc_buf, ctypes.POINTER(ctypes.c_uint8))
            asc_ptrs = (ctypes.POINTER(ctypes.c_uint8) * 1)(asc_ptr)
            asc_sizes = (ctypes.c_uint32 * 1)(len(fallback))
            err = self._lib.aacDecoder_ConfigRaw(self._handle, asc_ptrs, asc_sizes)
        if err != 0:
            self.close()
            raise RuntimeError(f"aacDecoder_ConfigRaw failed with error: 0x{err:x}")

        # Enable high-quality error concealment (AAC_CONCEAL_METHOD = 0x0100)
        if hasattr(self._lib, "aacDecoder_SetParam"):
            with contextlib.suppress(Exception):
                self._lib.aacDecoder_SetParam(self._handle, 0x0100, 1)

        # Safe 8192-sample buffer (~16 KB) prevents heap corruption under 512/1024/2048 sample frames
        self._out_buf = (ctypes.c_int16 * 8192)()

    def _init_api(self) -> None:
        self._lib.aacDecoder_Open.restype = ctypes.c_void_p
        self._lib.aacDecoder_Open.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

        self._lib.aacDecoder_ConfigRaw.restype = ctypes.c_uint32
        self._lib.aacDecoder_ConfigRaw.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
            ctypes.POINTER(ctypes.c_uint32),
        ]

        if hasattr(self._lib, "aacDecoder_SetParam"):
            self._lib.aacDecoder_SetParam.restype = ctypes.c_int32
            self._lib.aacDecoder_SetParam.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32]

        self._lib.aacDecoder_Fill.restype = ctypes.c_uint32
        self._lib.aacDecoder_Fill.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]

        self._lib.aacDecoder_DecodeFrame.restype = ctypes.c_uint32
        self._lib.aacDecoder_DecodeFrame.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.c_uint32,
        ]

        self._lib.aacDecoder_GetStreamInfo.restype = ctypes.POINTER(CStreamInfo)
        self._lib.aacDecoder_GetStreamInfo.argtypes = [ctypes.c_void_p]

        self._lib.aacDecoder_Close.restype = None
        self._lib.aacDecoder_Close.argtypes = [ctypes.c_void_p]

    def decode(self, au: bytes) -> bytes:
        """Decode one AAC-ELD access unit into signed 16-bit stereo PCM bytes."""
        if not au or self._handle is None or len(au) <= 4:
            return b""

        p_buf = (ctypes.c_uint8 * len(au)).from_buffer_copy(au)
        p_ptr = ctypes.cast(p_buf, ctypes.POINTER(ctypes.c_uint8))
        p_ptrs = (ctypes.POINTER(ctypes.c_uint8) * 1)(p_ptr)
        p_sizes = (ctypes.c_uint32 * 1)(len(au))
        p_valid = ctypes.c_uint32(len(au))

        fill_res = self._lib.aacDecoder_Fill(self._handle, p_ptrs, p_sizes, ctypes.byref(p_valid))
        if fill_res != 0:
            logger.debug("aacDecoder_Fill error: 0x%x", fill_res)
            return b""

        dec_res = self._lib.aacDecoder_DecodeFrame(
            self._handle, ctypes.cast(self._out_buf, ctypes.c_void_p), len(self._out_buf), 0
        )
        # Fraunhofer FDK-AAC specification:
        # AAC_DEC_CONCEAL = 0x4000
        # #define IS_OUTPUT_VALID(err) (((err) == 0) || (((err) & 0x4000) != 0))
        # When dec_res has bit 0x4000 set, error concealment was applied and output buffer
        # contains valid extrapolated audio samples. Only reject if dec_res is a fatal error.
        if dec_res != 0 and not (dec_res & 0x4000):
            logger.debug("aacDecoder_DecodeFrame fatal error: 0x%x", dec_res)
            return b""

        info_ptr = self._lib.aacDecoder_GetStreamInfo(self._handle)
        if not info_ptr:
            return b""
        info = info_ptr.contents
        valid_samples = info.frameSize * info.numChannels
        if valid_samples <= 0 or valid_samples > len(self._out_buf):
            return b""

        return ctypes.string_at(self._out_buf, valid_samples * 2)

    def close(self) -> None:
        if hasattr(self, "_handle") and self._handle:
            with contextlib.suppress(Exception):
                self._lib.aacDecoder_Close(self._handle)
            self._handle = None

    def __del__(self) -> None:
        self.close()


class FastAacEldDecoder:
    """Cross-platform AAC-ELD -> s16le stereo 48 kHz PCM decoder using PyAV (fallback)."""

    def __init__(self, magic_cookie: bytes = AAC_ELD_ASC_48K_STEREO_480) -> None:
        self._codec: Any = av.codec.CodecContext.create("aac", "r")
        try:
            self._codec.extradata = magic_cookie
            self._codec.open()
        except Exception:
            if magic_cookie == AAC_ELD_ASC_48K_STEREO_480:
                self._codec = av.codec.CodecContext.create("aac", "r")
                self._codec.extradata = bytes([0xF8, 0xE6, 0x50, 0x00])
                self._codec.open()
            else:
                raise
        self._resampler: Any = av.AudioResampler(format="s16", layout="stereo", rate=48000)

    def decode(self, au: bytes) -> bytes:
        """Decode one AAC-ELD Access Unit into raw signed 16-bit interleaved stereo PCM."""
        if not au:
            return b""
        packet = av.Packet(au)
        pcm_chunks: list[bytes] = []
        try:
            frames = self._codec.decode(packet)
            for frame in frames:
                resampled = self._resampler.resample(frame)
                for out_frame in resampled:
                    pcm_chunks.append(bytes(out_frame.planes[0]))
        except Exception as e:
            logger.debug("AAC-ELD decode frame drop: %s", e)
        return b"".join(pcm_chunks)

    def close(self) -> None:
        self._codec = None
        self._resampler = None


def create_aac_eld_decoder(magic_cookie: bytes = AAC_ELD_ASC_48K_STEREO_480) -> Any:
    """Factory creating FdkAacEldDecoder if native library exists, else FastAacEldDecoder."""
    try:
        return FdkAacEldDecoder(magic_cookie)
    except Exception as e:
        logger.debug("FdkAacEldDecoder not used (%s), using FastAacEldDecoder", e)
        return FastAacEldDecoder(magic_cookie)


class AudioStreamEngine:
    """CoreDevice iOS System Audio receiver and real-time playback streamer."""

    def __init__(
        self,
        rsd: Any,
        client_session_id: uuid.UUID,
        on_pcm: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self._rsd = rsd
        self._client_session_id = client_session_id
        self._on_pcm = on_pcm

        self._running: bool = False
        self._svc: Optional[DisplayService] = None
        self._transport: Optional[UdpMediaTransport] = None
        self._decoder: Optional[FastAacEldDecoder] = None

        self._local_ssrc: int = 0
        self._remote_ssrc: int = 0
        self._rtp_highest_seq: int = 0
        self._rtp_packets_received: int = 0
        self._rtcp_dest: Optional[Tuple[str, int]] = None

        self._jitter_queue: dict[int, bytes] = {}
        self._expected_seq: int = 0
        self._last_sample_l: int = 0
        self._last_sample_r: int = 0
        self._consecutive_errors: int = 0
        self._stat_pcm_bytes: int = 0
        self._stat_pkts: int = 0
        self._last_stat_t: float = 0.0

        self._rtcp_task: Optional[asyncio.Task[None]] = None
        self._recv_task: Optional[asyncio.Task[None]] = None

    def _generate_silence_frame(self, num_samples: int = 480) -> bytes:
        """Generate a short 10ms (480 stereo frames = 1920 bytes) silence frame with smooth fade-out.

        Bridges packet loss gaps to maintain continuous 48 kHz playback clock without pop/click artifacts.
        """
        frame_bytes = num_samples * 4  # 480 frames * 4 bytes/frame = 1920 bytes
        if self._last_sample_l == 0 and self._last_sample_r == 0:
            return b"\x00" * frame_bytes

        # Smooth fade-out over 32 frames (128 bytes) from last known audio level to silence
        fade_frames = min(32, num_samples)
        out_samples: list[int] = []
        for i in range(fade_frames):
            alpha = (i + 1) / fade_frames
            l_val = int((1.0 - alpha) * self._last_sample_l)
            r_val = int((1.0 - alpha) * self._last_sample_r)
            out_samples.extend((l_val, r_val))

        self._last_sample_l = 0
        self._last_sample_r = 0

        fade_data = struct.pack(f"<{len(out_samples)}h", *out_samples)
        remaining_silence = b"\x00" * (frame_bytes - len(fade_data))
        return fade_data + remaining_silence

    def _build_audio_rtcp_rr(self) -> bytes:
        """Construct RFC 3550 RTCP Receiver Report + SDES CNAME compound packet for audio."""
        rr = struct.pack(
            "!BBHIIIIIII",
            0x80 | 1,  # V=2, P=0, RC=1
            201,       # RR (Receiver Report)
            7,         # length in 32-bit words minus 1
            self._local_ssrc & 0xFFFFFFFF,
            self._remote_ssrc & 0xFFFFFFFF,
            0,         # fraction lost & cumulative lost
            self._rtp_highest_seq & 0xFFFFFFFF,
            0,         # jitter
            0,         # last SR timestamp
            0,         # delay since last SR
        )
        sdes = struct.pack(
            "!BBHI BBBB",
            0x81,      # V=2, P=0, SC=1
            202,       # SDES
            2,         # 3 words = 12 bytes
            self._local_ssrc & 0xFFFFFFFF,
            0x01,      # CNAME item
            0x00,      # length 0
            0x00,      # END item
            0x00,      # null pad to 32-bit boundary
        )
        return rr + sdes

    async def _rtcp_keepalive_loop(self) -> None:
        """Send periodic RTCP Receiver Reports every 1.0s to prevent iOS from reaping the audio session."""
        while self._running:
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

            if self._transport and self._rtcp_dest and self._local_ssrc and self._remote_ssrc:
                try:
                    packet = self._build_audio_rtcp_rr()
                    await self._transport.sendto(packet, *self._rtcp_dest)
                except Exception as e:
                    logger.debug("Audio RTCP RR send error: %s", e)

    def _dispatch_audio_payload(self, payload: bytes) -> None:
        """Decode and dispatch one AAC-ELD payload into signed 16-bit PCM."""
        if not self._decoder:
            return
        try:
            pcm = self._decoder.decode(payload)
            self._consecutive_errors = 0
            if not pcm:
                # If decode returned empty (e.g. corruption or concealment failure),
                # insert a short faded silence frame to maintain 48 kHz playback clock
                pcm = self._generate_silence_frame()

            if pcm and self._on_pcm:
                self._on_pcm(pcm)
                self._stat_pcm_bytes += len(pcm)
                if len(pcm) >= 4:
                    self._last_sample_l, self._last_sample_r = struct.unpack_from("<hh", pcm, len(pcm) - 4)
            self._stat_pkts += 1

            now = asyncio.get_running_loop().time()
            if now - self._last_stat_t >= 5.0:
                kb_s = (self._stat_pcm_bytes / max(0.001, (now - self._last_stat_t))) / 1024
                logger.info(
                    "Audio stream active: %d pkts, %d KB PCM dispatched (%.1f KB/s)",
                    self._stat_pkts,
                    self._stat_pcm_bytes // 1024,
                    kb_s,
                )
                self._stat_pcm_bytes = 0
                self._stat_pkts = 0
                self._last_stat_t = now
        except Exception as exc:
            self._consecutive_errors += 1
            logger.debug("Audio decode failed (%s) -- packet dropped", exc)
            if self._consecutive_errors >= 5:
                logger.warning("Audio decoder stuck after %d errors -- recreating", self._consecutive_errors)
                try:
                    self._decoder.close()
                    self._decoder = create_aac_eld_decoder(AAC_ELD_ASC_48K_STEREO_480)
                    self._consecutive_errors = 0
                except Exception as e:
                    logger.warning("Audio decoder recreation failed: %s", e)

    async def _udp_recv_loop(self, transport: UdpMediaTransport) -> None:
        """High-speed UDP packet receiver for RTP audio streams with jitter reordering."""
        try:
            self._decoder = create_aac_eld_decoder(AAC_ELD_ASC_48K_STEREO_480)
            logger.info("AudioStreamEngine decoder ready: %s -> s16le 48 kHz stereo", type(self._decoder).__name__)
        except Exception as e:
            logger.warning("Failed to initialize AAC-ELD decoder: %s", e)
            return

        self._consecutive_errors = 0
        self._last_stat_t = asyncio.get_running_loop().time()
        self._stat_pcm_bytes = 0
        self._stat_pkts = 0
        self._jitter_queue.clear()
        self._expected_seq = 0

        while self._running:
            try:
                data = await transport.recv(65535)
            except asyncio.CancelledError:
                return
            except (ConnectionResetError, OSError) as e:
                # Windows Winsock 10054 (WSAECONNRESET) occurs when an ICMP Port Unreachable packet is received
                # after sending early RTCP keepalive packets. Do NOT exit the receive loop!
                if getattr(e, "winerror", None) == 10054 or getattr(e, "errno", None) == 10054 or isinstance(e, ConnectionResetError):
                    await asyncio.sleep(0.01)
                    continue
                logger.debug("Audio UDP recv error: %s", e)
                return
            except Exception:
                logger.exception("Audio recv loop exception")
                return

            if len(data) < 12:
                continue

            pt = data[1] & 0x7F
            if 64 <= pt <= 95:  # RTCP packets
                continue

            self._rtp_packets_received += 1
            seq = int.from_bytes(data[2:4], "big")
            cur_ext = self._rtp_highest_seq
            cycles = (cur_ext >> 16) & 0xFFFF
            last_seq16 = cur_ext & 0xFFFF
            if seq < last_seq16 and (last_seq16 - seq) > 0x8000:
                cycles = (cycles + 1) & 0xFFFF
            new_ext = (cycles << 16) | seq
            if cur_ext == 0 or ((new_ext - cur_ext) & 0xFFFFFFFF) < 0x80000000:
                self._rtp_highest_seq = new_ext

            cc = data[0] & 0x0F
            header_len = 12 + cc * 4
            if data[0] & 0x10:  # RTP Header extension
                if header_len + 4 > len(data):
                    continue
                ext_len = int.from_bytes(data[header_len + 2 : header_len + 4], "big")
                header_len += 4 + ext_len * 4

            payload = data[header_len:]
            if not payload or len(payload) <= 4:
                continue

            # Jitter buffer & packet reordering:
            if self._expected_seq == 0:
                self._expected_seq = new_ext

            # Drop duplicate or stale packets already dispatched
            if new_ext < self._expected_seq and (self._expected_seq - new_ext) < 1000:
                continue

            self._jitter_queue[new_ext] = payload

            # Dispatch sequential packets in exact order
            while self._expected_seq in self._jitter_queue:
                pkt_payload = self._jitter_queue.pop(self._expected_seq)
                self._expected_seq += 1
                self._dispatch_audio_payload(pkt_payload)

            # If backlog exceeds 6 packets (~60ms), advance over missing packet to preserve realtime lip-sync
            if len(self._jitter_queue) > 6:
                silence_frame = self._generate_silence_frame()
                if silence_frame and self._on_pcm:
                    self._on_pcm(silence_frame)
                    self._stat_pcm_bytes += len(silence_frame)

                min_seq = min(self._jitter_queue.keys())
                self._expected_seq = min_seq
                while self._expected_seq in self._jitter_queue:
                    pkt_payload = self._jitter_queue.pop(self._expected_seq)
                    self._expected_seq += 1
                    self._dispatch_audio_payload(pkt_payload)

            # Cap jitter queue to prevent unbounded growth during extreme network bursts
            if len(self._jitter_queue) > 30:
                self._jitter_queue.clear()
                self._expected_seq = new_ext + 1

    async def start(self) -> bool:
        """Establish the audio stream with iOS CoreDevice DisplayService."""
        self._running = True
        try:
            self._svc = DisplayService(self._rsd)
            await self._svc.connect()

            # Allocate 2MB buffer for UDP audio packets to prevent kernel drops
            transport, receiver_ip = open_media_receiver(self._svc, (2 * 1024 * 1024, 1024 * 1024))
            self._transport = transport

            # Disable SIO_UDP_CONNRESET on Windows to prevent Winsock from raising 10054 on recv
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
                logger.debug("Audio userspace receiver IP check: %s", e)

            sender_ip = self._rsd.service.address[0]
            logger.info("Initiating audio stream: receiver=%s:%d, sender=%s", receiver_ip, transport.port, sender_ip)

            answer = await self._svc.start_audio_stream(
                receiver_ip=receiver_ip,
                receiver_port=transport.port,
                sender_ip=sender_ip,
                client_session_id=self._client_session_id,
            )

            cfg = answer.get("connection", {}).get("streamConfig", {})
            source_port = int(cfg.get("SourcePort", 0))
            self._local_ssrc = int(cfg.get("RemoteSSRC", 0))
            self._remote_ssrc = int(cfg.get("LocalSSRC", 0))
            self._rtcp_dest = (sender_ip, source_port) if source_port else None

            logger.info("Audio stream established. Sender port: %s, LocalSSRC: %s", source_port, self._local_ssrc)

            self._rtcp_task = asyncio.create_task(self._rtcp_keepalive_loop())
            self._recv_task = asyncio.create_task(self._udp_recv_loop(transport))
            return True
        except Exception as e:
            logger.warning("Failed to start audio stream (iPhone may not support audio or session error): %s", e)
            self.stop()
            return False

    def stop(self) -> None:
        """Stop audio streaming and release decoder/socket resources."""
        self._running = False
        self._jitter_queue.clear()
        self._expected_seq = 0
        self._last_sample_l = 0
        self._last_sample_r = 0
        if self._rtcp_task and not self._rtcp_task.done():
            self._rtcp_task.cancel()
            self._rtcp_task = None
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            self._recv_task = None
        if self._decoder:
            self._decoder.close()
            self._decoder = None
        if self._transport:
            t = self._transport
            self._transport = None
            with contextlib.suppress(Exception):
                res = t.close()
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_running():
                            loop.create_task(res)
                        else:
                            res.close()
                    except RuntimeError:
                        res.close()
        if self._svc:
            svc_to_close = self._svc
            self._svc = None
            with contextlib.suppress(Exception):
                if hasattr(svc_to_close, "close"):
                    res = svc_to_close.close()
                    if asyncio.iscoroutine(res):
                        try:
                            loop = asyncio.get_running_loop()
                            if loop.is_running():
                                loop.create_task(res)
                            else:
                                res.close()
                        except RuntimeError:
                            res.close()
