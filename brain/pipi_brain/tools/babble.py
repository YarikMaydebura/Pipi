"""A synthetic robot "babble" voice: lets you test talking animations without any API call.

The sound is a warbling tone with syllable-like loudness bumps (~4.5 per second), so the pet's
amplitude-driven animation moves the way it will with real speech. Deterministic (no noise).
"""

from __future__ import annotations

import numpy as np

from pipi_brain.speech.audio_utils import float_to_pcm16
from pipi_brain.speech.base import SpeechAudio

BABBLE_RATE = 24000  # same rate as tts-1 pcm output
CHARS_PER_S = 14.0  # roughly normal speaking speed
MIN_DURATION_S = 0.6
SYLLABLES_PER_S = 4.5
FADE_S = 0.02
LOUDNESS = 0.35


def babble(text: str, sample_rate: int = BABBLE_RATE) -> SpeechAudio:
    duration_s = max(MIN_DURATION_S, len(text) / CHARS_PER_S)
    t = np.arange(int(duration_s * sample_rate), dtype=np.float64) / sample_rate
    # Syllables: loudness bumps whose rate drifts a little, with short pauses between them.
    syllable_phase = 2 * np.pi * SYLLABLES_PER_S * t + 1.7 * np.sin(2 * np.pi * 0.6 * t)
    envelope = np.clip(np.sin(syllable_phase), 0, None) ** 1.5
    # Pitch glides around 190 Hz like a cheerful little robot voice.
    pitch_hz = 190 + 45 * np.sin(2 * np.pi * 1.3 * t) + 20 * np.sin(2 * np.pi * 3.1 * t)
    phase = 2 * np.pi * np.cumsum(pitch_hz) / sample_rate
    tone = np.sin(phase) + 0.35 * np.sin(2 * phase) + 0.15 * np.sin(3 * phase)
    fade = np.clip(np.minimum(t, t[-1] - t) / FADE_S, 0, 1) if t.size else t
    samples = (LOUDNESS / 1.5 * tone * envelope * fade).astype(np.float32)
    return SpeechAudio(pcm16=float_to_pcm16(samples), sample_rate=sample_rate)
