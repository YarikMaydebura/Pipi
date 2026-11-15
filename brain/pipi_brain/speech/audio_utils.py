"""Small audio conversions: float samples <-> 16-bit PCM <-> WAV, loudness in dBFS."""

from __future__ import annotations

import io
import math
import wave

import numpy as np

from pipi_brain.speech.base import Samples

SILENCE_DBFS = -120.0


def float_to_pcm16(samples: Samples) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767).astype("<i2").tobytes()


def pcm16_to_float(pcm16: bytes) -> Samples:
    usable = len(pcm16) - (len(pcm16) % 2)  # ignore a dangling odd byte
    ints = np.frombuffer(pcm16[:usable], dtype="<i2")
    return (ints.astype(np.float32) / 32768.0).astype(np.float32)


def pcm16_to_wav(pcm16: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16)
    return buffer.getvalue()


def samples_to_wav(samples: Samples, sample_rate: int) -> bytes:
    return pcm16_to_wav(float_to_pcm16(samples), sample_rate)


def rms_dbfs(samples: Samples) -> float:
    if samples.size == 0:
        return SILENCE_DBFS
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return 20 * math.log10(rms) if rms > 0 else SILENCE_DBFS
