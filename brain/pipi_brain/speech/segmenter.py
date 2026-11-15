"""Turn a stream of (frame, speech probability) into utterances.

Pure logic, no audio device and no model, so it is fully unit-tested.

- Speech starts when the probability reaches ``threshold``. ``pre_roll_ms`` of audio from just
  before is kept so the first syllable is not cut off.
- Speech ends after ``end_silence_ms`` of frames below ``threshold - 0.15`` (hysteresis, as in
  Silero's own segmenter, so a word with a soft ending does not end the utterance).
- Utterances with less than ``min_speech_ms`` of speech (coughs, clicks) are dropped.
- At ``max_utterance_s`` the utterance is cut and returned with ``truncated=True``.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from pipi_brain.config import VadConfig
from pipi_brain.speech.base import AudioFrame, Utterance

HYSTERESIS = 0.15


class UtteranceSegmenter:
    def __init__(self, config: VadConfig, *, sample_rate: int, frame_samples: int) -> None:
        self._sample_rate = sample_rate
        self._frame_ms = frame_samples / sample_rate * 1000
        self._threshold = config.threshold
        self._low_threshold = max(config.threshold - HYSTERESIS, 0.01)
        self._end_silence_ms = config.end_silence_ms
        self._min_speech_ms = config.min_speech_ms
        self._max_ms = config.max_utterance_s * 1000
        self._pre_roll: deque[AudioFrame] = deque(
            maxlen=math.ceil(config.pre_roll_ms / self._frame_ms)
        )
        self.reset()

    @property
    def in_speech(self) -> bool:
        return self._frames is not None

    def reset(self) -> None:
        self._pre_roll.clear()
        self._frames: list[AudioFrame] | None = None
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._started_at = 0.0

    def push(self, frame: AudioFrame, probability: float) -> Utterance | None:
        """Feed one frame. Returns an Utterance when one has just ended, else None."""
        if self._frames is None:
            if probability < self._threshold:
                self._pre_roll.append(frame)
                return None
            self._frames = [*self._pre_roll, frame]
            self._pre_roll.clear()
            self._started_at = frame.captured_at
            self._speech_ms = self._frame_ms
            self._silence_ms = 0.0
            return None

        self._frames.append(frame)
        if probability >= self._threshold:
            self._speech_ms += self._frame_ms
            self._silence_ms = 0.0
        elif probability < self._low_threshold or self._silence_ms > 0:
            self._silence_ms += self._frame_ms
        else:  # between the two thresholds while still talking: counts as speech
            self._speech_ms += self._frame_ms

        total_ms = len(self._frames) * self._frame_ms
        if self._silence_ms >= self._end_silence_ms:
            return self._finish(frame, truncated=False)
        if total_ms >= self._max_ms:
            return self._finish(frame, truncated=True)
        return None

    def _finish(self, last: AudioFrame, *, truncated: bool) -> Utterance | None:
        frames = self._frames or []
        long_enough = self._speech_ms >= self._min_speech_ms
        started_at = self._started_at
        self.reset()
        if not long_enough:
            return None
        return Utterance(
            samples=np.concatenate([f.samples for f in frames]).astype(np.float32),
            sample_rate=self._sample_rate,
            started_at=started_at,
            ended_at=last.captured_at,
            truncated=truncated,
        )
