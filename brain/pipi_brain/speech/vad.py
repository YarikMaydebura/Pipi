"""Voice activity detection: Silero VAD (ONNX) with a loudness-based fallback.

Why ONNX and not torch: ``onnxruntime`` is a ~15 MB wheel on Windows and macOS, while torch is
hundreds of MB. The Silero model (~2.3 MB) is downloaded once into the gitignored ``cache/``
folder and verified by SHA-256 (see ``vad.model_*`` in config/base.yaml).

If the model cannot be downloaded or loaded, :func:`create_vad` falls back to
:class:`EnergyVad` and reports why, so the caller can log it. The session keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pipi_brain.config import VadConfig
from pipi_brain.resilience import describe_error
from pipi_brain.speech.audio_utils import rms_dbfs
from pipi_brain.speech.base import Samples, VoiceActivityDetector
from pipi_brain.speech.model_cache import ensure_model

SILERO_STATE_SHAPE = (2, 1, 128)


class SileroVad:
    """Silero VAD v5 ONNX model, one 32 ms frame per call (same steps as Silero's OnnxWrapper).

    v5 expects each frame prefixed with the last 64 samples (16 kHz) of the previous frame
    and carries a recurrent ``state`` between calls.
    """

    name = "silero"

    def __init__(self, model_path: Path, *, sample_rate: int, frame_samples: int) -> None:
        import onnxruntime as ort  # imported here: tests and the energy fallback do not need it

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._sr = np.array(sample_rate, dtype=np.int64)
        self._frame_samples = frame_samples
        self._context_size = 64 if sample_rate == 16000 else 32
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros(SILERO_STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros((1, self._context_size), dtype=np.float32)

    def speech_probability(self, samples: Samples) -> float:
        frame = np.asarray(samples, dtype=np.float32).reshape(1, -1)
        if frame.shape[1] != self._frame_samples:
            raise ValueError(f"Silero needs {self._frame_samples} samples, got {frame.shape[1]}")
        model_input = np.concatenate([self._context, frame], axis=1)
        output, state = self._session.run(
            None, {"input": model_input, "state": self._state, "sr": self._sr}
        )
        self._state = state
        self._context = model_input[:, -self._context_size :]
        return float(output[0][0])


class EnergyVad:
    """Fallback: a frame louder than ``threshold_dbfs`` counts as speech (probability 1)."""

    name = "energy"

    def __init__(self, threshold_dbfs: float) -> None:
        self._threshold_dbfs = threshold_dbfs

    def reset(self) -> None:
        """Stateless."""

    def speech_probability(self, samples: Samples) -> float:
        return 1.0 if rms_dbfs(samples) >= self._threshold_dbfs else 0.0


@dataclass(frozen=True)
class VadChoice:
    vad: VoiceActivityDetector
    fallback_reason: str | None  # None = the configured engine is in use


def create_vad(config: VadConfig, *, sample_rate: int, frame_samples: int) -> VadChoice:
    """Build the configured VAD. Blocking (may download the model): run it in a thread."""
    energy = EnergyVad(config.energy_threshold_dbfs)
    if config.engine == "energy":
        return VadChoice(energy, None)
    try:
        model = ensure_model(
            config.model_path,
            url=config.model_url,
            sha256=config.model_sha256,
            timeout_s=config.download_timeout_s,
        )
        silero = SileroVad(model, sample_rate=sample_rate, frame_samples=frame_samples)
    except Exception as exc:  # missing model, no network, broken onnxruntime -> keep working
        return VadChoice(energy, f"Silero VAD unavailable ({describe_error(exc)})")
    return VadChoice(silero, None)
