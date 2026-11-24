"""Fake implementations of every external dependency: no network, no audio hardware.

Used by the tests; also handy to run logic offline. Each fake records what it was asked to do,
so tests can check behaviour (e.g. "TTS was asked to say the fallback line").
Scripted answers may be values or exceptions; an exception is raised instead of returned.
"""

from __future__ import annotations

import asyncio
import heapq
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from pipi_brain.bodies.base import NOT_CONNECTED, BodyResult, Entrance, Exit, SpeakResult
from pipi_brain.dialogue.prompts import ChatMessage
from pipi_brain.phases.inputs import TypedLine
from pipi_brain.protocol import Expression, EyeState, PersonaOption
from pipi_brain.speech.bang import Bang
from pipi_brain.speech.base import (
    AudioFrame,
    MicrophoneError,
    Samples,
    SpeechAudio,
)
from pipi_brain.vision.base import Blink, VisionCheck

FAKE_TTS_RATE = 24000


def make_frames(
    segments: Iterable[tuple[float, int]],
    *,
    frame_samples: int = 512,
    sample_rate: int = 16000,
    start_at: float = 100.0,
) -> list[AudioFrame]:
    """Frames from (amplitude, frame_count) segments, e.g. [(0, 10), (0.5, 20), (0, 30)].

    Amplitude 0 = silence; > 0 = a sine "voice". ``captured_at`` advances 32 ms per frame.
    """
    frame_s = frame_samples / sample_rate
    t = np.arange(frame_samples, dtype=np.float32) / sample_rate
    frames: list[AudioFrame] = []
    for amplitude, count in segments:
        samples = (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        for _ in range(count):
            frames.append(AudioFrame(samples.copy(), start_at + len(frames) * frame_s))
    return frames


def _next_scripted(script: list[object], name: str) -> object:
    if not script:
        raise AssertionError(f"{name}: no scripted answer left")
    item = script.pop(0)
    if isinstance(item, BaseException):
        raise item
    return item


class FakeMicrophone:
    """Plays back scripted frames; raises MicrophoneError when they run out (like a dead mic)."""

    def __init__(self, frames: Sequence[AudioFrame], sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self._frames = list(frames)
        self.started = False
        self.closed = False

    def add_frames(self, frames: Sequence[AudioFrame]) -> None:
        self._frames.extend(frames)

    async def start(self) -> None:
        self.started = True

    async def read_frame(self, timeout_s: float) -> AudioFrame:
        await asyncio.sleep(0)
        if not self._frames:
            raise MicrophoneError("fake microphone has no more frames")
        return self._frames.pop(0)

    def drain(self) -> int:
        return 0  # scripted frames are never stale

    async def close(self) -> None:
        self.closed = True


class FakeVad:
    """Probability 1.0 for frames louder than ``min_amplitude``, else 0.0."""

    name = "fake"

    def __init__(self, min_amplitude: float = 0.05) -> None:
        self._min_amplitude = min_amplitude
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def speech_probability(self, samples: Samples) -> float:
        return 1.0 if float(np.max(np.abs(samples), initial=0.0)) > self._min_amplitude else 0.0


@dataclass
class FakeSpeechToText:
    answers: list[object] = field(default_factory=list)  # str or Exception
    delay_s: float = 0.0
    calls: list[bytes] = field(default_factory=list)

    async def transcribe(self, wav: bytes) -> str:
        self.calls.append(wav)
        await asyncio.sleep(self.delay_s)
        return str(_next_scripted(self.answers, "FakeSpeechToText"))


@dataclass
class FakeTextToSpeech:
    """Returns silence (10 ms per character); ``failures`` lists exceptions to raise first."""

    failures: list[BaseException] = field(default_factory=list)
    delay_s: float = 0.0
    texts: list[str] = field(default_factory=list)

    async def synthesize(self, text: str) -> SpeechAudio:
        self.texts.append(text)
        await asyncio.sleep(self.delay_s)
        if self.failures:
            raise self.failures.pop(0)
        samples = int(FAKE_TTS_RATE * 0.01 * len(text))
        return SpeechAudio(pcm16=b"\x00\x00" * samples, sample_rate=FAKE_TTS_RATE)


@dataclass
class FakeSpeaker:
    fail_with: BaseException | None = None
    delay_s: float = 0.0
    on_play: Callable[[], None] | None = None  # e.g. check the audio gate during playback
    played: list[SpeechAudio] = field(default_factory=list)
    stops: int = 0

    async def play(self, audio: SpeechAudio) -> None:
        if self.on_play is not None:
            self.on_play()
        await asyncio.sleep(self.delay_s)
        if self.fail_with is not None:
            raise self.fail_with
        self.played.append(audio)

    def stop(self) -> None:
        self.stops += 1


@dataclass
class FakeChatModel:
    """Scripted raw model answers (JSON strings) or exceptions, in order."""

    answers: list[object] = field(default_factory=list)
    delay_s: float = 0.0
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def complete_json(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        await asyncio.sleep(self.delay_s)
        return str(_next_scripted(self.answers, "FakeChatModel"))


@dataclass
class FakeTextInput:
    """Typed lines; None (or running out) means the user quit."""

    lines: list[str | None] = field(default_factory=list)

    async def read_line(self) -> str | None:
        await asyncio.sleep(0)
        return self.lines.pop(0) if self.lines else None


@dataclass
class FakeBody:
    """A Body that records every call. ``connected=False`` behaves like a missing pet."""

    name: str = "desktop_pet"
    connected: bool = True
    speak_delivered: bool = True
    stop_ok: bool = True  # False = the body does not ack `stop` (old workaround is used)
    on_speak: Callable[[], None] | None = None  # e.g. check the audio gate during speech
    # set = when persona cards are shown, the participant clicks this target right away
    persona_click: str | None = None
    click_listeners: list[Callable[[str], None]] = field(default_factory=list)
    calls: list[tuple[str, object]] = field(default_factory=list)
    spoken: list[tuple[str, SpeechAudio | None, str]] = field(default_factory=list)

    async def wait_connected(self, timeout_s: float) -> bool:
        await asyncio.sleep(0)
        return self.connected

    def _result(self, name: str, arg: object) -> BodyResult:
        self.calls.append((name, arg))
        return BodyResult(ok=True) if self.connected else BodyResult(ok=False, error=NOT_CONNECTED)

    async def activate(self, entrance: Entrance) -> BodyResult:
        return self._result("activate", entrance)

    async def deactivate(self, exit: Exit) -> BodyResult:
        return self._result("deactivate", exit)

    async def set_eyes(self, state: EyeState) -> BodyResult:
        return self._result("eyes", state)

    async def play_motion(self, name: str) -> BodyResult:
        return self._result("motion", name)

    async def show_caption(self, text: str | None) -> BodyResult:
        return self._result("caption", text)

    async def speak(
        self, text: str, audio: SpeechAudio | None, expression: Expression = "idle"
    ) -> SpeakResult:
        self.calls.append(("speak", text))
        if self.on_speak is not None:
            self.on_speak()
        await asyncio.sleep(0)
        if not (self.connected and self.speak_delivered):
            error = NOT_CONNECTED if not self.connected else "body refused: test"
            return SpeakResult(delivered=False, finished=False, error=error)
        self.spoken.append((text, audio, expression))
        duration = round(audio.duration_s * 1000) if audio is not None else 0
        return SpeakResult(delivered=True, finished=True, duration_ms=duration)

    async def set_calm(self, on: bool) -> BodyResult:
        return self._result("calm", on)

    async def show_persona_picker(self, options: Sequence[PersonaOption]) -> BodyResult:
        result = self._result("persona_picker", list(options))
        if options and self.persona_click and self.connected:
            asyncio.get_running_loop().call_soon(self.click, self.persona_click)
        return result

    def subscribe_clicks(self, listener: Callable[[str], None]) -> Callable[[], None]:
        self.click_listeners.append(listener)
        return lambda: self.click_listeners.remove(listener)

    def click(self, target: str) -> None:
        """The participant clicks something on this body (a persona card: "persona:<id>")."""
        for listener in list(self.click_listeners):
            listener(target)

    async def stop(self) -> BodyResult:
        result = self._result("stop", None)
        if result.ok and not self.stop_ok:
            return BodyResult(ok=False, error="no ack within 1 s", timed_out=True)
        return result

    def health(self) -> str:
        return "connected (fake)" if self.connected else NOT_CONNECTED


class FakeClock:
    """Virtual time for session tests: ``sleep`` waits until the clock passes its deadline.

    ``autojump()`` (run as a task) moves time straight to the next deadline whenever every
    other task is idle, so a 4-minute timer takes milliseconds and always behaves the same.
    ``advance(s)`` moves time by hand instead.
    """

    def __init__(self, start: float = 1000.0, idle_yields: int = 200) -> None:
        self._now = start
        self._idle_yields = idle_yields
        self._waiters: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = 0

    def now(self) -> float:
        return self._now

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._seq += 1
        heapq.heappush(self._waiters, (self._now + seconds, self._seq, future))
        await future

    def _wake_next(self, until: float | None = None) -> bool:
        while self._waiters and self._waiters[0][2].done():
            heapq.heappop(self._waiters)  # cancelled sleeps
        if not self._waiters or (until is not None and self._waiters[0][0] > until):
            return False
        deadline, _, future = heapq.heappop(self._waiters)
        self._now = max(self._now, deadline)
        future.set_result(None)
        return True

    async def _settle(self) -> None:
        for _ in range(self._idle_yields):
            await asyncio.sleep(0)

    async def advance(self, seconds: float) -> None:
        target = self._now + seconds
        await self._settle()
        while self._wake_next(until=target):
            await self._settle()
        self._now = max(self._now, target)
        await self._settle()

    async def autojump(self) -> None:
        while True:
            await self._settle()
            self._wake_next()


@dataclass
class FakeBangDetector:
    """Scripted bangs for the duel, on the session's (virtual) clock.

    One item per ``wait_for_bang`` call: seconds after arming until the bang, ``None`` (the
    participant never shoots: waits until cancelled) or an exception (e.g.
    ``BangDetectorError``). When the script runs out, nobody shoots.
    """

    clock: FakeClock
    script: list[object] = field(default_factory=list)
    level_db: float = -6.0
    armed: int = 0

    def now(self) -> float:
        return self.clock.now()

    async def wait_for_bang(self) -> Bang:
        self.armed += 1
        item = self.script.pop(0) if self.script else None
        if isinstance(item, BaseException):
            await asyncio.sleep(0)
            raise item
        if item is None:
            await asyncio.Event().wait()  # never shoots (until cancelled)
        await self.clock.sleep(float(item))  # type: ignore[arg-type]
        return Bang(at=self.clock.now(), level_db=self.level_db)


@dataclass
class FakeBlinkDetector:
    """Scripted blinks for the staring contest, on the session's (virtual) clock.

    ``vision`` is what ``check()`` reports (default: detect mode possible). One script item
    per ``wait_for_blink`` call: seconds after arming until the blink, ``None`` (never blinks:
    waits until cancelled) or an exception (e.g. ``BlinkDetectorError``).
    """

    clock: FakeClock
    script: list[object] = field(default_factory=list)
    vision: VisionCheck = field(default_factory=lambda: VisionCheck(ok=True, fps=30.0))
    armed: int = 0
    checks: int = 0
    closed: bool = False

    def now(self) -> float:
        return self.clock.now()

    async def check(self) -> VisionCheck:
        self.checks += 1
        await asyncio.sleep(0)
        return self.vision

    async def wait_for_blink(self) -> Blink:
        self.armed += 1
        item = self.script.pop(0) if self.script else None
        if isinstance(item, BaseException):
            await asyncio.sleep(0)
            raise item
        if item is None:
            await asyncio.Event().wait()  # never blinks (until cancelled)
        await self.clock.sleep(float(item))  # type: ignore[arg-type]
        return Blink(at=self.clock.now())

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeUserInput:
    """What the participant says in a session test, one item per listening turn.

    Items: text (typed line, answered at once), an ``Utterance`` (goes through STT),
    ``(item, delay_s)`` (answer after a virtual delay; if the listening turn ends earlier, the
    answer comes in a later turn after the rest of the delay) or ``None`` (stays silent: this
    listening turn only ends by a timeout). When the script runs out, the participant is silent.
    """

    script: list[object] = field(default_factory=list)
    clock: FakeClock | None = None
    mode: Literal["voice", "typed"] = "typed"
    hearing: bool = False
    asked: int = 0

    async def next_input(self) -> object:
        self.asked += 1
        item = self.script.pop(0) if self.script else None
        if item is None:
            await asyncio.Event().wait()  # silent until cancelled
        if isinstance(item, tuple):
            text, delay_s = item
            if self.clock is not None:
                started = self.clock.now()
                try:
                    await self.clock.sleep(float(delay_s))
                except asyncio.CancelledError:
                    left = float(delay_s) - (self.clock.now() - started)
                    self.script.insert(0, (text, max(0.0, left)))  # still about to say it
                    raise
            item = text
        if isinstance(item, str):
            return TypedLine(item)
        return item
