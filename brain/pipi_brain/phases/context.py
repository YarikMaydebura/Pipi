"""PhaseContext: everything a phase handler may use, plus small helpers they all need.

A phase handler is ``async def run(ctx: PhaseContext) -> Next``. It speaks with
``ctx.say_line`` / ``conversation.reply``, listens with ``conversation.listen``, waits with
pausable countdowns, and returns which phase comes next. The controller does the rest
(logging the phase change, WoZ interrupts, side changes).
"""

from __future__ import annotations

import asyncio
import random
import string
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pipi_brain.bodies.base import Body
from pipi_brain.bodies.manager import BodyManager
from pipi_brain.config import AppConfig, SessionConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.dialogue.prompts import PromptBody
from pipi_brain.games.registry import GameRegistry
from pipi_brain.games.setup import GameSetup
from pipi_brain.memory import Memory, MemoryUpdates
from pipi_brain.phases.clock import Clock, cancel_and_wait
from pipi_brain.phases.events import SessionEvents
from pipi_brain.phases.flow import Trigger
from pipi_brain.phases.inputs import UserInputSource
from pipi_brain.phases.state import SessionState
from pipi_brain.phases.timers import Countdown, PauseState, SafePoints
from pipi_brain.phases.voice import SayMeta, Voice
from pipi_brain.phases.woz_signals import WozSignals
from pipi_brain.protocol import Expression, Phase
from pipi_brain.speech.bang import BangDetector
from pipi_brain.speech.base import SpeechToText
from pipi_brain.vision.base import BlinkDetector

T = TypeVar("T")

PERSONAL_FIELDS = frozenset({"name"})  # lines filled with these are never disk-cached


@dataclass(frozen=True)
class Next:
    """What a phase handler returns: the next phase and why."""

    phase: Phase
    trigger: Trigger = "auto"


class MissingLineValue(Exception):
    """A fixed line needs a value (e.g. {name}) that is not known."""


@dataclass
class PhaseContext:
    app: AppConfig
    content: DialogueContent
    state: SessionState
    events: SessionEvents
    voice: Voice
    bodies: BodyManager
    stt: SpeechToText
    dialogue: DialogueEngine
    input: UserInputSource
    clock: Clock
    pause: PauseState
    safe: SafePoints
    games: GameSetup  # games.yaml, motions.yaml and the registry of built games
    rng: random.Random  # injected, so tests of the games are deterministic
    woz_signals: WozSignals  # motions the WoZ plays by hand (a game may wait for one)
    push_state: Callable[[], None]
    emit: Callable[[str], None]
    reading_text: str | None = None
    bang_detector: BangDetector | None = None  # quick-draw duel; None = typed / slow motion
    blink_detector: BlinkDetector | None = None  # staring contest (webcam); None = pretend

    @property
    def registry(self) -> GameRegistry:
        return self.games.registry

    @property
    def session(self) -> SessionConfig:
        return self.app.session

    # --- logging -------------------------------------------------------------------------------

    def log(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        self.events.log(event_type, data)

    def memory_reference(self, what: list[str]) -> None:
        """A deliberate identity cue: Pipi mentions something it remembers."""
        if what:
            self.log("memory_reference", {"what": what, "body": self.bodies.active_name})

    # --- memory --------------------------------------------------------------------------------

    def set_memory(self, memory: Memory, changed: list[str]) -> None:
        if not changed:
            return
        self.state.memory = memory
        # Values stay out of events.jsonl (privacy): only memory.json holds e.g. the name,
        # and from now on the logger writes the name as [NAME] (also in earlier events).
        self.events.logger.redact_name(memory.name)
        self.log("memory_update", {"fields": changed})
        self.events.logger.write_json("memory.json", memory.model_dump(mode="json"))
        self.push_state()

    def remember(self, updates: MemoryUpdates) -> None:
        memory, changed = self.state.memory.apply(updates)
        self.set_memory(memory, changed)

    # --- speaking ------------------------------------------------------------------------------

    def line(self, line_id: str, **values: str) -> str:
        """Persona variant of a fixed line with its {placeholders} filled."""
        text = self.content.line(line_id, self.state.persona)
        needed = {field for _, field, _, _ in string.Formatter().parse(text) if field}
        missing = sorted(needed - set(values))
        if missing:
            raise MissingLineValue(f"line {line_id!r} needs {', '.join(missing)}")
        return text.format(**values) if needed else text

    async def say_line(
        self,
        line_id: str,
        *,
        body: Body | None = None,
        gesture: str = "none",
        expression: Expression = "idle",
        fallback: str | None = None,
        start: float | None = None,
        stt_ms: int | None = None,
        source: str = "phase",
        respect_pause: bool = True,
        **values: str,
    ) -> None:
        text = self.line(line_id, **values)
        meta = SayMeta(
            line_id=line_id,
            expression=expression,
            gesture=gesture,
            fallback=fallback,
            start=start,
            stt_ms=stt_ms,
            source=source,
        )
        cacheable = not (PERSONAL_FIELDS & set(values))
        await self.voice.say(
            text, meta, body=body, cacheable=cacheable, respect_pause=respect_pause
        )

    def prompt_body(self) -> PromptBody:
        return "robot" if self.bodies.active_side == "robot" else "desktop_pet"

    # --- timing --------------------------------------------------------------------------------

    def countdown(self, name: str, seconds: float, *, visible: bool = True) -> Countdown:
        timer = Countdown(name, seconds, self.pause, self.clock)
        if visible:
            self.state.phase_timer = timer
            self.push_state()
        return timer

    async def wait(self, seconds: float) -> None:
        """Pausable wait."""
        await Countdown("wait", seconds, self.pause, self.clock).wait_expired()

    async def until(self, timer: Countdown, work: Callable[[], Awaitable[T]]) -> T | None:
        """Run ``work`` until it finishes or ``timer`` expires (then it is stopped at the next
        safe point, never mid-sentence). Returns the result, or None if the timer won."""
        work_task: asyncio.Task[T] = asyncio.ensure_future(work())
        timer_task = asyncio.ensure_future(timer.wait_expired())
        try:
            done, _ = await asyncio.wait(
                {work_task, timer_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if work_task in done:
                return work_task.result()
            await self.safe.interrupt(work_task)
            if work_task.done() and not work_task.cancelled():
                return work_task.result()  # finished right before the interrupt landed
            return None
        finally:
            await cancel_and_wait([work_task, timer_task])
