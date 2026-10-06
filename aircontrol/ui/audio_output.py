"""Low-latency audio playback manager using PySide6.QtMultimedia.QAudioSink on a dedicated thread."""

from __future__ import annotations

import logging
import struct
from typing import Optional

from PySide6.QtCore import QIODevice, QObject, QThread, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

logger = logging.getLogger(__name__)


class AudioWorker(QObject):
    """Audio worker running on dedicated QThread to isolate WASAPI I/O from the GUI thread."""

    def __init__(self, sample_rate: int = 48000, channels: int = 2) -> None:
        super().__init__()
        self._format = QAudioFormat()
        self._format.setSampleRate(sample_rate)
        self._format.setChannelCount(channels)
        self._format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        self._sink: Optional[QAudioSink] = None
        self._io: Optional[QIODevice] = None
        self._is_muted: bool = False
        self._volume: float = 1.0
        self._buffer: bytearray = bytearray()

    @Slot()
    def initialize(self) -> None:
        try:
            device = QMediaDevices.defaultAudioOutput()
            if not device or device.isNull():
                logger.warning("No default audio output device available")
                return

            self._sink = QAudioSink(device, self._format, self)
            # Low-latency 40ms buffer (~7,680 bytes) ensures tight A/V lip-sync with video stream
            self._sink.setBufferSize(48000 * 2 * 2 * 40 // 1000)
            self._sink.setVolume(self._volume if not self._is_muted else 0.0)
            self._io = self._sink.start()
            self._buffer.clear()
            logger.info("AudioWorker initialized on %s (48 kHz stereo, 40ms buffer)", device.description())
        except Exception as e:
            logger.warning("Failed to initialize QAudioSink on worker thread: %s", e)

    def _crossfade_compaction(self, excess: int) -> None:
        """Discard `excess` bytes from buffer with linear cross-fade to eliminate clicks/pops."""
        if excess <= 0:
            return

        fade_frames = min(32, excess // 4, (len(self._buffer) - excess) // 4)
        if fade_frames <= 0:
            del self._buffer[:excess]
            return

        fade_bytes = fade_frames * 4
        fade_samples = fade_frames * 2  # 2 channels (Int16)

        try:
            old_samples = struct.unpack_from(f"<{fade_samples}h", self._buffer, 0)
            new_samples = struct.unpack_from(f"<{fade_samples}h", self._buffer, excess)

            out_samples: list[int] = []
            for i in range(fade_frames):
                alpha = i / fade_frames
                # Left channel
                l_val = int((1.0 - alpha) * old_samples[2 * i] + alpha * new_samples[2 * i])
                # Right channel
                r_val = int((1.0 - alpha) * old_samples[2 * i + 1] + alpha * new_samples[2 * i + 1])
                out_samples.append(max(-32768, min(32767, l_val)))
                out_samples.append(max(-32768, min(32767, r_val)))

            struct.pack_into(f"<{fade_samples}h", self._buffer, excess, *out_samples)
            del self._buffer[:excess]
        except Exception as e:
            logger.debug("Error during cross-fade compaction: %s", e)
            del self._buffer[:excess]

    @Slot(bytes)
    def write_pcm(self, pcm_bytes: bytes) -> None:
        if self._is_muted or not self._io:
            return
        try:
            if not self._io.isOpen():
                return

            self._buffer.extend(pcm_bytes)

            free = self._sink.bytesFree() if self._sink else len(self._buffer)
            if free > 0:
                to_write = min(len(self._buffer), free)
                to_write = (to_write // 4) * 4  # Strictly preserve 4-byte 16-bit stereo frame boundary
                if to_write > 0:
                    written = self._io.write(bytes(self._buffer[:to_write]))
                    if written > 0:
                        del self._buffer[:written]

            # Elastic buffer compaction: if buffer exceeds 60ms (11520 bytes) due to soundcard stall,
            # apply linear cross-fade compaction to maintain lip-sync without clicks or popping.
            MAX_BUFFER_BACKLOG = 11520  # 60ms at 48kHz stereo (48000 * 2 * 2 * 60 // 1000)
            if len(self._buffer) > MAX_BUFFER_BACKLOG:
                excess = ((len(self._buffer) - MAX_BUFFER_BACKLOG) // 4) * 4
                if excess > 0:
                    self._crossfade_compaction(excess)
        except Exception as e:
            logger.debug("Error writing audio PCM in worker: %s", e)

    @Slot(bool)
    def set_muted(self, muted: bool) -> None:
        self._is_muted = muted
        if self._sink:
            self._sink.setVolume(0.0 if muted else self._volume)

    @Slot(float)
    def set_volume(self, vol: float) -> None:
        self._volume = max(0.0, min(1.0, vol))
        if self._sink and not self._is_muted:
            self._sink.setVolume(self._volume)

    @Slot()
    def close(self) -> None:
        self._buffer.clear()
        if self._sink:
            self._sink.stop()
            self._sink = None
            self._io = None


class AudioOutputManager(QObject):
    """Manages system audio playback through laptop speakers with volume and mute controls.

    Uses a background QThread to eliminate startup freeze and prevent cross-thread
    lock contention with OpenGL rendering.
    """

    _chunk_signal = Signal(bytes)
    _mute_signal = Signal(bool)
    _volume_signal = Signal(float)
    _close_signal = Signal()

    mute_changed = Signal(bool)
    volume_changed = Signal(float)

    def __init__(self, parent: Optional[QObject] = None, *, auto_start: Optional[bool] = None) -> None:
        super().__init__(parent)
        self._is_muted: bool = False
        self._volume: float = 1.0
        self._io: Optional[QIODevice] = None  # Mock hook for unit testing

        self._thread: Optional[QThread] = None
        self._worker: Optional[AudioWorker] = None

        if auto_start is None:
            import os
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            is_offscreen = (
                os.environ.get("QT_QPA_PLATFORM") == "offscreen"
                or (app is not None and app.platformName() == "offscreen")
            )
            auto_start = not is_offscreen

        if auto_start:
            self._thread = QThread()
            self._worker = AudioWorker()
            self._worker.moveToThread(self._thread)

            self._thread.started.connect(self._worker.initialize)
            self._chunk_signal.connect(self._worker.write_pcm)
            self._mute_signal.connect(self._worker.set_muted)
            self._volume_signal.connect(self._worker.set_volume)
            self._close_signal.connect(self._worker.close)

            self._thread.start()

    def write_pcm(self, pcm_bytes: bytes) -> None:
        """Write signed 16-bit stereo PCM chunk (1920-2048 bytes) to audio device."""
        if self._is_muted:
            return
        if self._io is not None:
            try:
                self._io.write(pcm_bytes)
            except Exception as e:
                logger.debug("Error writing audio PCM: %s", e)
            return
        self._chunk_signal.emit(pcm_bytes)

    def set_muted(self, muted: bool) -> None:
        self._is_muted = muted
        self._mute_signal.emit(muted)
        self.mute_changed.emit(self._is_muted)

    def toggle_mute(self) -> bool:
        self.set_muted(not self._is_muted)
        return self._is_muted

    def set_volume(self, vol: float) -> None:
        self._volume = max(0.0, min(1.0, vol))
        self._volume_signal.emit(self._volume)
        self.volume_changed.emit(self._volume)

    @property
    def is_muted(self) -> bool:
        return self._is_muted

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def _sink(self) -> Optional[QAudioSink]:
        return self._worker._sink if self._worker else None

    def close(self) -> None:
        if self._thread is not None:
            if self._thread.isRunning():
                self._close_signal.emit()
                self._thread.quit()
                if not self._thread.wait(1500):
                    self._thread.terminate()
                    self._thread.wait(500)
            self._thread = None
            self._worker = None

    def __del__(self) -> None:
        self.close()

