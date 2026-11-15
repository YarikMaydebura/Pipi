"""Pipi speaking: text -> speech (cached for fixed lines) -> the active body, with fallbacks.

Rules (docs/INTERACTION_FLOW.md §3, SYSTEM_DESIGN.md §10):
- one speaker at a time: a lock, and every utterance is a safe point (never cut by WoZ),
- the microphone is gated while Pipi talks (half-duplex),
- fixed lines come from the TTS disk cache; lines with participant data are synthesized live,
- TTS failure -> captions only; body missing / refuses -> laptop speaker (``body_fallback``),
- every utterance is a ``turn`` event (with latencies) and is pushed to the WoZ panel,
- thinking eyes appear when a reply takes longer than ``thinking_delay_ms``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any

from pipi_brain.bodies.base import NOT_CONNECTED, Body
from pipi_brain.bodies.manager import BodyManager
from pipi_brain.latency import TurnLatency
from pipi_brain.phases.clock import Clock
from pipi_brain.phases.events import SessionEvents
from pipi_brain.phases.timers import PauseState, SafePoints
from pipi_brain.protocol import Expression, Turn, TurnLatencies
from pipi_brain.resilience import CallOutcome, elapsed_ms_since, timed_call
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.base import Speaker, SpeechAudio, TextToSpeech
from pipi_brain.speech.tts_cache import CachedSpeech, TtsCache


@dataclass(frozen=True)
class SayMeta:
    line_id: str | None = None  # set for fixed lines
    expression: Expression = "idle"
    gesture: str = "none"
    fallback: str | None = None  # why a fallback line was used (llm_fallback, stt_error, ...)
    start: float | None = None  # perf_counter when the participant's input arrived
    stt_ms: int | None = None
    llm_ms: int | None = None
    llm_attempts: int | None = None
    source: str = "phase"  # "phase" or "woz"


@dataclass(frozen=True)
class VoiceSettings:
    tts_timeout_s: float
    playback_margin_s: float
    thinking_delay_s: float


class Voice:
    def __init__(
        self,
        *,
        tts: TextToSpeech,
        cache: TtsCache | None,
        speaker: Speaker,
        gate: AudioGate,
        bodies: BodyManager,
        events: SessionEvents,
        safe: SafePoints,
        pause: PauseState,
        clock: Clock,
        settings: VoiceSettings,
        on_spoken: Callable[[str], None],
        on_latency: Callable[[TurnLatency], None],
        emit: Callable[[str], None],
    ) -> None:
        self._tts = tts
        self._cache = cache
        self._speaker = speaker
        self._gate = gate
        self._bodies = bodies
        self._events = events
        self._safe = safe
        self._pause = pause
        self._clock = clock
        self._settings = settings
        self._on_spoken = on_spoken
        self._on_latency = on_latency
        self._emit = emit
        self._lock = asyncio.Lock()
        self._prefetched: dict[str, asyncio.Task[CallOutcome[SpeechAudio]]] = {}
        self._thinking: asyncio.Task[None] | None = None

    # --- thinking eyes ------------------------------------------------------------------------

    def thinking_soon(self) -> None:
        """Show thinking eyes if Pipi has not started speaking within the delay."""
        self.cancel_thinking()
        self._thinking = asyncio.ensure_future(self._think_later())

    def cancel_thinking(self) -> None:
        if self._thinking is not None:
            self._thinking.cancel()
            self._thinking = None

    async def _think_later(self) -> None:
        await self._clock.sleep(self._settings.thinking_delay_s)
        await self._bodies.set_eyes("thinking")

    # --- speaking -----------------------------------------------------------------------------

    def prefetch(self, text: str) -> None:
        """Start synthesizing a live line early (kept in memory only), e.g. during a jump."""
        if text not in self._prefetched:
            self._prefetched[text] = asyncio.ensure_future(
                timed_call(lambda: self._tts.synthesize(text), self._settings.tts_timeout_s)
            )

    async def say(
        self,
        text: str,
        meta: SayMeta | None = None,
        *,
        body: Body | None = None,
        cacheable: bool = False,
        respect_pause: bool = True,
    ) -> None:
        """Speak one line on ``body`` (default: the active body). Never raises."""
        meta = meta or SayMeta()
        if respect_pause:
            await self._pause.wait_running()
        self.cancel_thinking()
        async with self._safe.critical(), self._lock:
            target = body if body is not None else self._bodies.active
            speech = await self._synthesize(text, cacheable)
            self._log_turn(text, meta, speech, target)
            self._on_spoken(text)
            await self._deliver(target, text, speech.audio, meta)

    def stop(self) -> None:
        """Emergency stop: silence the laptop speaker and drop pending work."""
        self.cancel_thinking()
        for task in self._prefetched.values():
            task.cancel()
        self._prefetched.clear()
        self._speaker.stop()

    async def _synthesize(self, text: str, cacheable: bool) -> CachedSpeech:
        task = self._prefetched.pop(text, None)
        if task is not None:
            outcome = await task
            speech = CachedSpeech(outcome.value, False, outcome.elapsed_ms, outcome.error)
        elif cacheable and self._cache is not None:
            speech = await self._cache.get(text)
        else:
            outcome = await timed_call(
                lambda: self._tts.synthesize(text), self._settings.tts_timeout_s
            )
            speech = CachedSpeech(
                outcome.value, False, outcome.elapsed_ms, outcome.error, outcome.timed_out
            )
        if speech.audio is None:
            self._events.log(
                "tts_error",
                {
                    "error": speech.error or "no audio",
                    "timed_out": speech.timed_out,
                    "fallback": "captions_only",
                },
            )
        return speech

    def _log_turn(
        self, text: str, meta: SayMeta, speech: CachedSpeech, target: Body | None
    ) -> None:
        data: dict[str, Any] = {
            "speaker": "pipi",
            "text": text,
            "tts_ms": speech.elapsed_ms,
            "tts_cached": speech.from_cache,
            "expression": meta.expression,
            "gesture": meta.gesture,
            "fallback_used": meta.fallback,
            "audio": speech.audio is not None,
            "source": meta.source,
        }
        if meta.line_id is not None:
            data["line_id"] = meta.line_id
        latencies: TurnLatencies | None = None
        if meta.start is not None:
            latency = TurnLatency(
                meta.stt_ms, meta.llm_ms, speech.elapsed_ms, elapsed_ms_since(meta.start)
            )
            self._on_latency(latency)
            data.update(stt_ms=meta.stt_ms, llm_ms=meta.llm_ms, total_ms=latency.total_ms)
            if meta.llm_attempts is not None:
                data["llm_attempts"] = meta.llm_attempts
            latencies = TurnLatencies(
                stt_ms=meta.stt_ms,
                llm_ms=meta.llm_ms,
                tts_ms=speech.elapsed_ms,
                total_ms=latency.total_ms,
            )
        self._events.log("turn", data, body=target.name if target is not None else None)
        self._events.push(Turn(speaker="pipi", text=text, latencies=latencies))
        self._emit(f"Pipi: {text}")

    async def _deliver(
        self, body: Body | None, text: str, audio: SpeechAudio | None, meta: SayMeta
    ) -> None:
        if body is not None and body.connected:
            if meta.gesture != "none":
                await self._bodies.play_motion(meta.gesture, body=body.name)
            gate: AbstractContextManager[None] = (
                self._gate.speaking() if audio is not None else nullcontext()
            )
            with gate:
                result = await body.speak(text, audio, meta.expression)
            if result.delivered:
                return
            error = result.error
        else:
            error = NOT_CONNECTED if body is not None else "no active body"
        fallback = "local_speaker" if audio is not None else "captions_only"
        self._events.log(
            "body_fallback",
            {
                "body": body.name if body is not None else None,
                "action": "speak",
                "error": error,
                "fallback": fallback,
            },
        )
        if audio is not None:
            await self._play(audio)

    async def _play(self, audio: SpeechAudio) -> None:
        timeout_s = audio.duration_s + self._settings.playback_margin_s
        with self._gate.speaking():
            outcome = await timed_call(lambda: self._speaker.play(audio), timeout_s)
            if outcome.timed_out:
                self._speaker.stop()
        if not outcome.ok:
            self._events.log(
                "audio_error",
                {"device": "speaker", "error": outcome.error, "fallback": "captions_only"},
            )
