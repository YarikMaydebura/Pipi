"""Listening: microphone frames -> audio gate -> VAD -> segmenter -> one Utterance."""

from __future__ import annotations

from collections.abc import Callable

from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.base import Microphone, Utterance, VoiceActivityDetector
from pipi_brain.speech.segmenter import UtteranceSegmenter


class AudioInput:
    def __init__(
        self,
        *,
        microphone: Microphone,
        vad: VoiceActivityDetector,
        segmenter: UtteranceSegmenter,
        gate: AudioGate,
        frame_timeout_s: float,
    ) -> None:
        self.microphone = microphone
        self.vad = vad
        self._segmenter = segmenter
        self._gate = gate
        self._frame_timeout_s = frame_timeout_s

    async def listen(
        self,
        start_timeout_s: float | None,
        on_speech_start: Callable[[], None] | None = None,
    ) -> Utterance | None:
        """Wait for one utterance.

        Returns None if nobody starts speaking within ``start_timeout_s`` (measured in audio
        time, from the first accepted frame). Once speech has started we wait for its end;
        ``vad.max_utterance_s`` bounds that. Raises MicrophoneError if the mic stops.
        """
        self.microphone.drain()  # audio from before we started listening is stale
        self.vad.reset()
        self._segmenter.reset()
        first_frame_at: float | None = None

        while True:
            frame = await self.microphone.read_frame(self._frame_timeout_s)
            if not self._gate.accepts(frame.captured_at):
                continue
            if first_frame_at is None:
                first_frame_at = frame.captured_at
            was_in_speech = self._segmenter.in_speech
            utterance = self._segmenter.push(frame, self.vad.speech_probability(frame.samples))
            if utterance is not None:
                return utterance
            if self._segmenter.in_speech and not was_in_speech and on_speech_start:
                on_speech_start()
            timed_out = (
                start_timeout_s is not None
                and frame.captured_at - first_frame_at >= start_timeout_s
            )
            if timed_out and not self._segmenter.in_speech:
                return None
