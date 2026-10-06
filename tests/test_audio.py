"""Unit tests for the Aircontrol audio subsystem."""

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest

from aircontrol.core.audio import (
    AudioStreamEngine,
    FastAacEldDecoder,
    FdkAacEldDecoder,
    create_aac_eld_decoder,
    AAC_ELD_ASC_48K_STEREO_480,
)
from aircontrol.ui.audio_output import AudioOutputManager


def test_fdk_aac_eld_decoder_lifecycle():
    decoder = create_aac_eld_decoder(AAC_ELD_ASC_48K_STEREO_480)
    assert decoder is not None

    # Empty payload should return empty bytes without error
    pcm = decoder.decode(b"")
    assert pcm == b""

    # Silent / keepalive frame (< 4 bytes)
    pcm = decoder.decode(b"\x00\x68\x34\x00")
    assert pcm == b""

    decoder.close()


def test_fast_aac_eld_decoder_lifecycle():
    decoder = FastAacEldDecoder(AAC_ELD_ASC_48K_STEREO_480)
    assert decoder._codec is not None
    assert decoder._resampler is not None

    # Empty payload should return empty bytes without error
    pcm = decoder.decode(b"")
    assert pcm == b""

    decoder.close()
    assert decoder._codec is None
    assert decoder._resampler is None


def test_audio_rtcp_packet_construction():
    mock_rsd = MagicMock()
    sid = uuid.uuid4()
    engine = AudioStreamEngine(rsd=mock_rsd, client_session_id=sid)

    engine._local_ssrc = 0x12345678
    engine._remote_ssrc = 0x87654321
    engine._rtp_highest_seq = 100

    packet = engine._build_audio_rtcp_rr()
    # RR (32 bytes) + SDES (12 bytes, matching Xcode mirror) = 44 bytes
    assert len(packet) == 44
    # Check RR payload type 201
    assert packet[1] == 201
    # Check SDES payload type 202
    assert packet[33] == 202


@pytest.mark.asyncio
async def test_audio_stream_engine_lifecycle():
    mock_rsd = MagicMock()
    mock_rsd.service.address = ["fd00::1"]
    sid = uuid.uuid4()
    pcm_chunks: list[bytes] = []

    def on_pcm(chunk: bytes) -> None:
        pcm_chunks.append(chunk)

    engine = AudioStreamEngine(rsd=mock_rsd, client_session_id=sid, on_pcm=on_pcm)

    mock_svc = AsyncMock()
    mock_svc.start_audio_stream.return_value = {
        "connection": {
            "streamConfig": {
                "SourcePort": 50000,
                "RemoteSSRC": 12345,
                "LocalSSRC": 67890,
            }
        }
    }

    mock_transport = AsyncMock()
    mock_transport.port = 48000

    with (
        patch("aircontrol.core.audio.DisplayService", return_value=mock_svc),
        patch("aircontrol.core.audio.open_media_receiver", return_value=(mock_transport, "::1")),
        patch("aircontrol.core.audio.create_aac_eld_decoder") as MockDecoder,
    ):
        mock_decoder_inst = MagicMock()
        mock_decoder_inst.decode.return_value = b"\x00" * 1920
        MockDecoder.return_value = mock_decoder_inst

        started = await engine.start()
        assert started
        assert engine._running
        assert engine._local_ssrc == 12345
        assert engine._remote_ssrc == 67890
        assert engine._rtcp_dest == ("fd00::1", 50000)

        # Stop engine
        engine.stop()
        assert not engine._running
        assert engine._transport is None


def test_audio_output_manager():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    mgr = AudioOutputManager(auto_start=False)

    # Initial state
    assert not mgr.is_muted
    assert mgr.volume == 1.0

    # Volume clamping
    mgr.set_volume(0.75)
    assert abs(mgr.volume - 0.75) < 0.01
    mgr.set_volume(1.5)
    assert mgr.volume == 1.0
    mgr.set_volume(-0.5)
    assert mgr.volume == 0.0

    # Toggle mute
    is_muted = mgr.toggle_mute()
    assert is_muted
    assert mgr.is_muted

    # Writing while muted should safely drop without writing to device
    mock_io = MagicMock()
    mgr._io = mock_io
    mgr.write_pcm(b"\x00" * 1920)
    assert not mock_io.write.called

    # Unmute
    mgr.set_muted(False)
    assert not mgr.is_muted
    mgr.write_pcm(b"\x00" * 1920)
    mgr.close()


@pytest.mark.asyncio
async def test_audio_udp_recv_loop_resilient_to_winerror_10054():
    """Verify that transient Winsock 10054 errors do NOT terminate the audio UDP recv loop."""
    mock_rsd = MagicMock()
    sid = uuid.uuid4()
    received_pcm: list[bytes] = []

    engine = AudioStreamEngine(rsd=mock_rsd, client_session_id=sid, on_pcm=lambda pcm: received_pcm.append(pcm))
    engine._running = True

    # Build a valid dummy RTP audio packet (payload type 101, seq 1, header 12 bytes + payload)
    # Header: V=2, P=0, X=0, CC=0 -> 0x80; M=0, PT=101 -> 0x65; seq=1; ts=0; ssrc=1
    rtp_header = struct.pack("!BBHII", 0x80, 101, 1, 0, 1)
    rtp_packet = rtp_header + b"\x00" * 32

    # Create mock transport whose recv raises WinError 10054 twice before returning data
    mock_transport = AsyncMock()
    win_err = OSError("Connection reset")
    win_err.winerror = 10054

    mock_transport.recv.side_effect = [
        win_err,
        win_err,
        rtp_packet,
        asyncio.CancelledError(),
    ]

    with patch("aircontrol.core.audio.create_aac_eld_decoder") as MockDecoder:
        mock_decoder = MagicMock()
        mock_decoder.decode.return_value = b"\x01\x02\x03\x04"
        MockDecoder.return_value = mock_decoder

        # Run recv loop directly and verify it survives the two 10054 errors
        await engine._udp_recv_loop(mock_transport)

        assert mock_transport.recv.await_count == 4
        assert len(received_pcm) == 1
        assert received_pcm[0] == b"\x01\x02\x03\x04"


def test_fdk_aac_eld_decoder_concealment_support():
    """Verify that Fraunhofer FDK-AAC decoder accepts concealment frames (0x4000 bit set)."""
    decoder = FdkAacEldDecoder(AAC_ELD_ASC_48K_STEREO_480)
    assert decoder._handle is not None

    # Mock lib calls to simulate concealment return code (e.g. 0x4002: AAC_DEC_CONCEAL | transport warning)
    mock_info = MagicMock()
    mock_info.contents.frameSize = 480
    mock_info.contents.numChannels = 2

    with (
        patch.object(decoder._lib, "aacDecoder_Fill", return_value=0),
        patch.object(decoder._lib, "aacDecoder_DecodeFrame", return_value=0x4002),
        patch.object(decoder._lib, "aacDecoder_GetStreamInfo", return_value=mock_info),
    ):
        pcm = decoder.decode(b"\x00" * 32)
        # Should return valid PCM buffer of length frameSize * numChannels * 2 = 1920 bytes
        assert len(pcm) == 480 * 2 * 2

    # Verify fatal error (e.g. 0x0020 with no 0x4000 bit) returns empty bytes
    with (
        patch.object(decoder._lib, "aacDecoder_Fill", return_value=0),
        patch.object(decoder._lib, "aacDecoder_DecodeFrame", return_value=0x0020),
    ):
        pcm_err = decoder.decode(b"\x00" * 32)
        assert pcm_err == b""

    decoder.close()


def test_audio_worker_buffer_and_drift_protection():
    """Verify AudioWorker low-latency buffer configuration and soft cross-fade compaction."""
    from aircontrol.ui.audio_output import AudioWorker
    worker = AudioWorker()
    assert worker._format.sampleRate() == 48000
    assert worker._format.channelCount() == 2

    # Verify 40ms low-latency buffer calculation (48000 * 2 * 2 * 40 // 1000 = 7680 bytes)
    expected_buf_size = 48000 * 2 * 2 * 40 // 1000
    assert expected_buf_size == 7680

    # Mock sink with 40ms buffer (7680 bytes)
    mock_sink = MagicMock()
    mock_sink.bufferSize.return_value = 7680
    mock_sink.bytesFree.return_value = 7680
    mock_io = MagicMock()
    mock_io.isOpen.return_value = True

    worker._sink = mock_sink
    worker._io = mock_io

    # 1. Normal write within capacity: must be written, never dropped
    worker.write_pcm(b"\x00" * 1920)
    assert mock_io.write.called

    # 2. Soundcard backlog / stall simulation: bytesFree = 0
    mock_sink.bytesFree.return_value = 0
    mock_io.reset_mock()

    # Feed 7 frames (7 * 1920 = 13440 bytes) while soundcard cannot take data
    for _ in range(7):
        worker.write_pcm(b"\x10\x00\x20\x00" * 480)

    # Elastic buffer soft compaction must cap buffer to MAX_BUFFER_BACKLOG (11520 bytes = 60ms)
    assert len(worker._buffer) == 11520
    # Frame alignment must remain strictly 4-byte aligned (Int16 stereo)
    assert len(worker._buffer) % 4 == 0

    # 3. Soundcard resumes and accepts audio
    mock_sink.bytesFree.return_value = 7680
    mock_io.write.side_effect = lambda data: len(data)
    worker.write_pcm(b"\x00" * 1920)
    assert mock_io.write.called
    assert len(worker._buffer) % 4 == 0


def test_audio_worker_100_frames_zero_drop():
    """Verify that a 100-frame continuous audio stream has 0% frame loss (no 37% drop)."""
    from aircontrol.ui.audio_output import AudioWorker
    worker = AudioWorker()

    mock_sink = MagicMock()
    mock_sink.bufferSize.return_value = 7680  # 40ms low-latency buffer
    mock_sink.bytesFree.return_value = 1920   # Room for 1 frame each write
    mock_io = MagicMock()
    mock_io.isOpen.return_value = True

    written_bytes = 0
    def handle_write(data: bytes) -> int:
        nonlocal written_bytes
        written_bytes += len(data)
        return len(data)

    mock_io.write.side_effect = handle_write
    worker._sink = mock_sink
    worker._io = mock_io

    # Send 100 continuous 10ms frames (1920 bytes each = 192,000 bytes)
    frame_size = 1920
    num_frames = 100
    for i in range(num_frames):
        chunk = struct.pack("<hh", i, -i) * 480
        worker.write_pcm(chunk)

    total_accounted = written_bytes + len(worker._buffer)
    assert total_accounted == num_frames * frame_size
    assert written_bytes == num_frames * frame_size
    assert len(worker._buffer) == 0
    assert mock_io.write.call_count == 100


def test_audio_worker_crossfade_compaction_smoothness():
    """Verify linear cross-fade compaction blends amplitude smoothly without clicks."""
    from aircontrol.ui.audio_output import AudioWorker
    worker = AudioWorker()

    # Fill buffer with high amplitude tone on left and negative on right
    high_samples = struct.pack("<hh", 10000, -10000) * 2880  # 11520 bytes
    new_samples = struct.pack("<hh", 20000, -20000) * 960   # 3840 bytes
    worker._buffer.extend(high_samples + new_samples)

    # Trigger compaction of excess 3840 bytes
    assert len(worker._buffer) == 15360
    worker._crossfade_compaction(3840)

    # Buffer must be reduced by 3840 bytes
    assert len(worker._buffer) == 11520
    assert len(worker._buffer) % 4 == 0

    # First frame of compacted buffer should be smoothly blended
    first_l, first_r = struct.unpack_from("<hh", worker._buffer, 0)
    # alpha=0 for first frame -> matches old sample
    assert first_l == 10000
    assert first_r == -10000


@pytest.mark.asyncio
async def test_audio_stream_engine_jitter_buffer_loss_and_silence_concealment():
    """Verify that after 6 missing packets, a smooth silence frame is generated."""
    mock_rsd = MagicMock()
    sid = uuid.uuid4()
    dispatched_pcm: list[bytes] = []

    engine = AudioStreamEngine(rsd=mock_rsd, client_session_id=sid, on_pcm=lambda pcm: dispatched_pcm.append(pcm))
    engine._running = True

    # Packet 1 arrives
    p1 = struct.pack("!BBHII", 0x80, 101, 1, 1000, 1) + b"PKT01"
    # Packet 2 is lost! Packets 3, 4, 5, 6, 7, 8, 9 arrive (7 packets in queue > 6)
    pkts = [p1]
    for seq in range(3, 10):
        pkts.append(struct.pack("!BBHII", 0x80, 101, seq, seq * 1000, 1) + f"PKT{seq:02d}".encode())

    mock_transport = AsyncMock()
    mock_transport.recv.side_effect = pkts + [asyncio.CancelledError()]

    with patch("aircontrol.core.audio.create_aac_eld_decoder") as MockDecoder:
        mock_decoder = MagicMock()
        mock_decoder.decode.return_value = b"\x01\x02\x03\x04" * 480
        MockDecoder.return_value = mock_decoder

        await engine._udp_recv_loop(mock_transport)

        # There should be 1 silence concealment frame (1920 bytes) generated for the lost packet
        # plus the 8 decoded packets (p1 and p3..p9)
        silence_frames = [f for f in dispatched_pcm if len(f) == 1920 and f.endswith(b"\x00" * (1920 - 128))]
        assert len(silence_frames) == 1
        assert len(dispatched_pcm) == 9


def test_audio_stream_engine_empty_decode_generates_silence_frame():
    """Verify that when decoder returns empty bytes, AudioStreamEngine inserts faded silence."""
    mock_rsd = MagicMock()
    sid = uuid.uuid4()
    dispatched_pcm: list[bytes] = []

    engine = AudioStreamEngine(rsd=mock_rsd, client_session_id=sid, on_pcm=lambda pcm: dispatched_pcm.append(pcm))
    engine._decoder = MagicMock()
    # Decoder returns empty bytes (unrecoverable or corrupted frame)
    engine._decoder.decode.return_value = b""

    # Dispatch audio payload
    engine._dispatch_audio_payload(b"\x00" * 32)

    # Must have generated 1920-byte silence frame to prevent clock drift
    assert len(dispatched_pcm) == 1
    assert len(dispatched_pcm[0]) == 1920
    assert dispatched_pcm[0] == b"\x00" * 1920


@pytest.mark.asyncio
async def test_audio_stream_engine_jitter_buffer_reordering():
    """Verify that out-of-order RTP audio packets are dispatched in strict sequence."""
    mock_rsd = MagicMock()
    sid = uuid.uuid4()
    dispatched_order: list[int] = []

    engine = AudioStreamEngine(rsd=mock_rsd, client_session_id=sid)
    engine._running = True

    # Packets with seq 10, seq 12, seq 11
    p10 = struct.pack("!BBHII", 0x80, 101, 10, 1000, 1) + b"PKT10"
    p11 = struct.pack("!BBHII", 0x80, 101, 11, 2000, 1) + b"PKT11"
    p12 = struct.pack("!BBHII", 0x80, 101, 12, 3000, 1) + b"PKT12"

    mock_transport = AsyncMock()
    # Deliver out of order: 10, 12, 11
    mock_transport.recv.side_effect = [p10, p12, p11, asyncio.CancelledError()]

    with patch("aircontrol.core.audio.create_aac_eld_decoder") as MockDecoder:
        mock_decoder = MagicMock()
        mock_decoder.decode.side_effect = lambda payload: dispatched_order.append(int(payload.decode()[3:])) or b"\x00" * 1920
        MockDecoder.return_value = mock_decoder

        await engine._udp_recv_loop(mock_transport)

        # Must have reordered into exact 10 -> 11 -> 12 sequence!
        assert dispatched_order == [10, 11, 12]


def test_audio_worker_fifo_ring_buffer_alignment():
    """Verify AudioWorker preserves 4-byte stereo frame alignment during partial writes."""
    from aircontrol.ui.audio_output import AudioWorker
    worker = AudioWorker()

    mock_sink = MagicMock()
    mock_sink.bufferSize.return_value = 12000
    mock_sink.bytesFree.return_value = 1002  # Not a multiple of 4
    mock_io = MagicMock()
    mock_io.isOpen.return_value = True

    # Simulate write returning only 1000 bytes (aligned to 4)
    def mock_write(data):
        return len(data)

    mock_io.write.side_effect = mock_write
    worker._sink = mock_sink
    worker._io = mock_io

    # Write 1920 bytes
    worker.write_pcm(b"\x01" * 1920)

    # Must only write 1000 bytes (min(1920, 1002) & ~3 = 1000)
    assert mock_io.write.called
    written_data = mock_io.write.call_args[0][0]
    assert len(written_data) == 1000
    assert len(written_data) % 4 == 0

    # Remaining 920 bytes must stay in internal buffer
    assert len(worker._buffer) == 920

    # Next write of 1920 bytes with full free buffer
    mock_sink.bytesFree.return_value = 28800
    worker.write_pcm(b"\x02" * 1920)
    # Total available was 920 + 1920 = 2840 bytes, fully written
    last_written = mock_io.write.call_args[0][0]
    assert len(last_written) == 2840
    assert len(worker._buffer) == 0




