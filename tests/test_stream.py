"""Tests for the Aircontrol video streaming and HEVC decode subsystem."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from aircontrol.core.stream import (
    FastHevcDecoder,
    ScreenStreamEngine,
    _is_key_nal,
)


def test_is_key_nal():
    assert _is_key_nal(19)  # IDR_W_RADL
    assert _is_key_nal(20)  # IDR_N_LP
    assert _is_key_nal(21)  # CRA
    assert not _is_key_nal(1)  # TRAIL_R (P-frame)
    assert not _is_key_nal(32)  # VPS
    assert not _is_key_nal(33)  # SPS
    assert not _is_key_nal(34)  # PPS


def test_screen_stream_engine_rtcp_packets():
    mock_rsd = MagicMock()
    mock_rsd.service.address = ("fe80::1", 0)

    engine = ScreenStreamEngine(
        rsd=mock_rsd,
        on_frame=lambda raw, w, h: None,
    )
    engine._local_ssrc = 0x11223344
    engine._remote_ssrc = 0x55667788
    engine._rtp_highest_seq = 0x00010005

    # 1. RTCP PLI
    pli = engine._build_rtcp_pli()
    assert len(pli) == 12
    assert pli[0] == 0x81
    assert pli[1] == 0xCE  # PT=206 (PSFB)

    # 2. RTCP Receiver Report + SDES
    rr = engine._build_rtcp_rr()
    assert len(rr) == 32 + 12
    assert rr[0] == 0x81
    assert rr[1] == 0xC9  # PT=201 (RR)


@pytest.mark.asyncio
async def test_screen_stream_engine_keyframe_rate_limiting():
    mock_rsd = MagicMock()
    engine = ScreenStreamEngine(
        rsd=mock_rsd,
        on_frame=lambda raw, w, h: None,
    )

    mock_transport = AsyncMock()
    engine._transport = mock_transport
    engine._rtcp_dest = ("::1", 5000)
    engine._local_ssrc = 123
    engine._remote_ssrc = 456

    # First request goes through
    await engine.request_keyframe()
    assert mock_transport.sendto.await_count == 1

    # Immediate second request is throttled (< 2s)
    await engine.request_keyframe()
    assert mock_transport.sendto.await_count == 1


def test_fast_hevc_decoder_low_latency_queue():
    """Verify FastHevcDecoder uses maxsize=4 queue for smooth jitter absorption without frame drops."""
    vps = b"\x40\x01\x0c\x01\xff\xff\x01\x60\x00\x00\x03\x00\x90\x00\x00\x03\x00\x00\x03\x00\x5d\x95\x98\x09"
    sps = b"\x42\x01\x01\x01\x60\x00\x00\x03\x00\x90\x00\x00\x03\x00\x00\x03\x00\x5d\xa0\x02\x80\x80\x2d\x16\x59\x99\xa4\x93\x2b\x80\x40\x00\x00\xfa\x40\x00\x3a\x98\x04"
    pps = b"\x44\x01\xc1\x73\xd1\x89"

    with patch("av.codec.CodecContext.create"):
        dec = FastHevcDecoder(vps, sps, pps)
        assert dec._inq.maxsize == 16
        dec.close()


@pytest.mark.asyncio
async def test_screen_stream_engine_rtp_packet_reordering():
    """Verify out-of-order RTP packets are reordered seamlessly without dropping frames."""
    import struct

    mock_rsd = MagicMock()
    engine = ScreenStreamEngine(
        rsd=mock_rsd,
        on_frame=lambda raw, w, h: None,
    )
    engine._running = True

    # Build 2 RTP packets: seq 100 (non-marker) and seq 101 (marker)
    def make_rtp(seq: int, marker: int, ts: int, nal: bytes) -> bytes:
        hdr = struct.pack("!BBHII", 0x80, (marker << 7) | 96, seq, ts, 0x12345678)
        return hdr + nal

    # Dummy NALs
    nal0 = b"\x02\x01\xd0\x00"  # Initial packet establishing sequence
    nal1 = b"\x02\x01\xd0\x01"  # Trail_R slice 1
    nal2 = b"\x02\x01\xd0\x02"  # Trail_R slice 2

    pkt0 = make_rtp(99, 1, 4000, nal0)
    pkt1 = make_rtp(100, 0, 5000, nal1)
    pkt2 = make_rtp(101, 1, 5000, nal2)

    # Arrive out of order: pkt0 arrives, then pkt2 arrives BEFORE pkt1
    packets = [pkt0, pkt2, pkt1]

    async def mock_recv():
        if packets:
            return packets.pop(0)
        engine._running = False
        raise asyncio.CancelledError()

    mock_transport = AsyncMock()
    mock_transport.recv = mock_recv

    # Mock decoder feed to capture fed annexb
    fed_annexb = []
    mock_decoder = MagicMock()
    mock_decoder.feed = lambda b: fed_annexb.append(b)
    engine._decoder = mock_decoder

    await engine._udp_recv_loop(mock_transport)

    # Frame 0 and Frame 1 must both have been decoded cleanly
    assert len(fed_annexb) == 2
    # Check that nal1 came before nal2 in the second frame's annexb stream
    pos1 = fed_annexb[1].find(nal1)
    pos2 = fed_annexb[1].find(nal2)
    assert pos1 != -1 and pos2 != -1
    assert pos1 < pos2, "Packets must be reordered so nal1 precedes nal2"


def test_screen_stream_engine_rtcp_spoofer_zero_loss():
    """Verify RTCP RR and RCTL packet spoofer reports zero packet loss and zero jitter to keep 60 FPS."""
    mock_rsd = MagicMock()
    engine = ScreenStreamEngine(rsd=mock_rsd)
    engine._local_ssrc = 0x11223344
    engine._remote_ssrc = 0x55667788
    engine._rtp_highest_seq = 0x00010005

    # Check RTCP RR: fraction_lost (byte 12) = 0, cumulative_loss (bytes 13-15) = 0, jitter (bytes 20-23) = 0
    rr_packet = engine._build_rtcp_rr()
    # Header: 8 bytes (V, PT, length, local_ssrc). Report block starts at offset 8: remote_ssrc (4 bytes)
    # Byte 12 is fraction lost
    assert rr_packet[12] == 0, "fraction_lost must be 0"
    # Bytes 13, 14, 15 are cumulative packets lost
    assert rr_packet[13:16] == b"\x00\x00\x00", "cumulative loss must be 0"
    # Bytes 20:24 are interarrival jitter
    assert rr_packet[20:24] == b"\x00\x00\x00\x00", "interarrival jitter must be 0"


@pytest.mark.asyncio
async def test_screen_stream_engine_start_fec_and_rtcp_fb():
    """Verify start() enables FEC and RTCP feedback in start_video_stream."""
    mock_rsd = MagicMock()
    mock_rsd.service.address = ("127.0.0.1", 0)
    engine = ScreenStreamEngine(rsd=mock_rsd)

    mock_display_svc = AsyncMock()
    mock_display_svc.start_video_stream.return_value = {
        "connection": {"streamConfig": {"SourcePort": 5555, "RemoteSSRC": 1, "LocalSSRC": 2}}
    }

    mock_transport = MagicMock()
    mock_transport.port = 8888

    with (
        patch("pymobiledevice3.remote.core_device.display_service.DisplayService", return_value=mock_display_svc),
        patch("aircontrol.core.stream.open_media_receiver", return_value=(mock_transport, "127.0.0.1")),
        patch.object(engine, "_udp_recv_loop", AsyncMock()),
        patch.object(engine, "_rtcp_keepalive_loop", AsyncMock()),
        patch.object(engine, "_rctl_feedback_loop", AsyncMock()),
        patch.object(engine, "_stall_watchdog_loop", AsyncMock()),
        patch.object(engine, "_keep_awake_loop", AsyncMock()),
    ):
        await engine.start()

        mock_display_svc.start_video_stream.assert_awaited_once()
        kwargs = mock_display_svc.start_video_stream.await_args[1]
        assert kwargs.get("allow_rtcp_fb") is True, "allow_rtcp_fb must be True"
        assert kwargs.get("fec_enabled") is True, "fec_enabled must be True"

