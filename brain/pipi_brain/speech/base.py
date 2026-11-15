"""Speech data types and the interfaces of every speech dependency.

Real implementations: ``devices.py`` (microphone, speaker via sounddevice), ``vad.py``
(Silero / energy), ``stt.py`` (gpt-4o-mini-transcribe), ``tts.py`` (gpt-4o-mini-tts).
Fakes for tests and offline runs: ``pipi_brain.fakes``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

Samples = npt.NDArray[np.float32]  # mono audio, values in [-1, 1]


@dataclass(frozen=True, eq=False)
class AudioFrame:
    samples: Samples
    captured_at: float  # time.monotonic() seconds when the frame arrived from the device


@dataclass(frozen=True, eq=False)
class Utterance:
    samples: Samples
    sample_rate: int
    started_at: float  # monotonic time speech was first detected
    ended_at: float  # monotonic time the end of speech was detected
    truncated: bool  # True if cut off at vad.max_utterance_s

    @property
    def duration_ms(self) -> int:
        return round(len(self.samples) / self.sample_rate * 1000)


@dataclass(frozen=True)
class SpeechAudio:
    """Synthesized speech as raw 16-bit little-endian mono PCM."""

    pcm16: bytes
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return len(self.pcm16) / 2 / self.sample_rate


class MicrophoneError(Exception):
    """The microphone could not be opened or stopped delivering audio."""


class SpeakerError(Exception):
    """Audio could not be played."""


class Microphone(Protocol):
    sample_rate: int

    async def start(self) -> None: ...

    async def read_frame(self, timeout_s: float) -> AudioFrame:
        """Next frame; raises MicrophoneError if none arrives within ``timeout_s``."""
        ...

    def drain(self) -> int:
        """Drop frames that were captured but not read yet; returns how many."""
        ...

    async def close(self) -> None: ...


class Speaker(Protocol):
    async def play(self, audio: SpeechAudio) -> None:
        """Play and return when playback has finished."""
        ...

    def stop(self) -> None:
        """Stop playback immediately (used after a playback timeout)."""
        ...


class VoiceActivityDetector(Protocol):
    name: str

    def speech_probability(self, samples: Samples) -> float:
        """Probability 0..1 that this frame contains speech."""
        ...

    def reset(self) -> None:
        """Forget internal state (call before each new listening period)."""
        ...


class SpeechToText(Protocol):
    async def transcribe(self, wav: bytes) -> str: ...


class TextToSpeech(Protocol):
    async def synthesize(self, text: str) -> SpeechAudio: ...
