"""Real microphone and speaker via ``sounddevice`` (PortAudio; wheels for Windows and macOS).

``sounddevice`` is imported lazily so tests and typed-input runs never touch audio hardware.
The microphone callback runs on a PortAudio thread; frames are handed to the asyncio loop
with ``call_soon_threadsafe`` and cut into exact VAD-sized frames.
"""

from __future__ import annotations

import asyncio
import time
from types import ModuleType
from typing import Any

import numpy as np

from pipi_brain.resilience import describe_error, with_timeout
from pipi_brain.speech.audio_utils import pcm16_to_float
from pipi_brain.speech.base import AudioFrame, MicrophoneError, SpeakerError, SpeechAudio

MAX_QUEUED_SECONDS = 20  # older frames are dropped if nobody reads them


def import_sounddevice() -> ModuleType:
    try:
        import sounddevice
    except OSError as exc:  # PortAudio library missing (rare on Win/macOS: wheels bundle it)
        raise MicrophoneError(f"audio library unavailable: {describe_error(exc)}") from exc
    return sounddevice


def describe_audio_devices() -> str:
    """Text table of audio devices (for ``--list-audio-devices``)."""
    return str(import_sounddevice().query_devices())


class SoundDeviceMicrophone:
    def __init__(self, *, sample_rate: int, frame_samples: int, device: str | int | None) -> None:
        self.sample_rate = sample_rate
        self._frame_samples = frame_samples
        self._device = device
        max_frames = int(MAX_QUEUED_SECONDS * sample_rate / frame_samples)
        self._queue: asyncio.Queue[AudioFrame] = asyncio.Queue(maxsize=max_frames)
        self._pending = np.zeros(0, dtype=np.float32)  # only touched by the PortAudio thread
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: Any = None
        self.status_warnings = 0  # PortAudio over/underflow count, for the log

    async def start(self) -> None:
        sd = import_sounddevice()
        self._loop = asyncio.get_running_loop()
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self._frame_samples,
                device=self._device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:  # PortAudioError, invalid device, permission denied
            raise MicrophoneError(f"cannot open microphone: {describe_error(exc)}") from exc

    def _callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        if status:
            self.status_warnings += 1
        captured_at = time.monotonic()
        self._pending = np.concatenate([self._pending, indata[:, 0].astype(np.float32)])
        while len(self._pending) >= self._frame_samples:
            chunk = self._pending[: self._frame_samples].copy()
            self._pending = self._pending[self._frame_samples :]
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._enqueue, AudioFrame(chunk, captured_at))

    def _enqueue(self, frame: AudioFrame) -> None:
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(frame)

    async def read_frame(self, timeout_s: float) -> AudioFrame:
        try:
            return await with_timeout(self._queue.get(), timeout_s)
        except TimeoutError as exc:
            raise MicrophoneError(f"no audio from the microphone for {timeout_s:g} s") from exc

    def drain(self) -> int:
        dropped = 0
        while not self._queue.empty():
            self._queue.get_nowait()
            dropped += 1
        return dropped

    async def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None


class SoundDeviceSpeaker:
    def __init__(self, *, device: str | int | None) -> None:
        self._device = device

    async def play(self, audio: SpeechAudio) -> None:
        samples = pcm16_to_float(audio.pcm16)
        if samples.size == 0:
            return
        await asyncio.to_thread(self._play_blocking, samples, audio.sample_rate)

    def _play_blocking(self, samples: np.ndarray, sample_rate: int) -> None:
        sd = import_sounddevice()
        try:
            sd.play(samples, samplerate=sample_rate, device=self._device)
            sd.wait()
        except Exception as exc:  # PortAudioError, invalid device
            raise SpeakerError(f"cannot play audio: {describe_error(exc)}") from exc

    def stop(self) -> None:
        try:
            import_sounddevice().stop()
        except Exception:  # stopping is best effort; the playback error is already logged
            return
