"""What the session lends a game: ``SessionGameContext`` (the real ``games.base.GameContext``).

A game never touches the session directly. Through this class it can speak (same voice,
same logging as every phase), listen, move the active body (motion names go through
``motions.yaml``), ask the LLM for a small JSON answer, log and remember.

Two rules are enforced here, in code:
- **No speech while acting.** Inside ``with ctx.silence(...)`` every ``say`` / ``say_line`` is
  blocked: nothing reaches the body or the speaker, and a ``game_rule_blocked`` event is
  logged. Listening is quiet there too (no "could you say that again?").
- **Pause / stop.** Waits are pausable countdowns and listening freezes on WoZ pause, like in
  every other phase.

``woz_motion`` lets a game wait for a motion the experimenter plays by hand (the quick-draw
duel uses it so the WoZ can score a round with the existing ``play_motion`` command; see
``woz_signals.py``).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Literal, TypeVar

from pipi_brain.games.base import ChatMessage, Heard
from pipi_brain.games.config import GamesConfig
from pipi_brain.memory import Memory
from pipi_brain.phases import conversation
from pipi_brain.phases.context import PhaseContext
from pipi_brain.phases.voice import SayMeta
from pipi_brain.protocol import Expression, EyeState
from pipi_brain.speech.bang import BangDetector
from pipi_brain.vision.base import BlinkDetector

T = TypeVar("T")
ACTING_GROUP = "crocodile"  # motions.yaml group of the act_* motions


def capabilities(ctx: PhaseContext) -> frozenset[str]:
    """What games can rely on right now (compared with ``Game.requires``)."""
    found = {"speech"}
    body = ctx.bodies.active_name
    if ctx.games.motions.supports(body):
        found.add("motions")
    if ctx.games.motions.supports(body, ACTING_GROUP):
        found.add("acting_motions")  # the act_* motions of Crocodile (robot bodies only)
    if ctx.input.mode == "voice":
        found.add("microphone")
        if ctx.bang_detector is not None:
            found.add("bang_detector")
    if ctx.blink_detector is not None:
        found.add("camera")  # the staring contest can watch for blinks (webcam)
    return frozenset(found)


class SessionGameContext:
    def __init__(self, ctx: PhaseContext) -> None:
        self._ctx = ctx
        self.rng: random.Random = ctx.rng
        self.config: GamesConfig = ctx.games.config
        self._silences: list[str] = []

    # --- what the game can find out ------------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._ctx.app.mode

    @property
    def capabilities(self) -> frozenset[str]:
        return capabilities(self._ctx)

    @property
    def input_mode(self) -> Literal["voice", "typed"]:
        return self._ctx.input.mode

    @property
    def hearing(self) -> bool:
        return self._ctx.input.hearing

    @property
    def bang_detector(self) -> BangDetector | None:
        return self._ctx.bang_detector if self._ctx.input.mode == "voice" else None

    @property
    def blink_detector(self) -> BlinkDetector | None:
        return self._ctx.blink_detector

    @property
    def memory(self) -> Memory:
        return self._ctx.state.memory

    @property
    def halted(self) -> bool:
        return self._ctx.state.halted

    def now(self) -> float:
        """Session time without the paused stretches (so a WoZ pause never eats a timeout)."""
        return self._ctx.pause.active_now()

    # --- speaking (blocked while silent) -------------------------------------------------------

    @contextmanager
    def silence(self, reason: str) -> Iterator[None]:
        self._silences.append(reason)
        try:
            yield
        finally:
            self._silences.pop()

    def _blocked(self, what: str) -> bool:
        if not self._silences:
            return False
        self._ctx.log(
            "game_rule_blocked",
            {"rule": "no_speech", "during": self._silences[-1], "blocked": what},
        )
        return True

    async def say(
        self, text: str, *, gesture: str = "none", expression: Expression = "idle"
    ) -> None:
        if self._blocked("say"):
            return
        meta = SayMeta(gesture=self._gesture(gesture), expression=expression)
        await self._ctx.voice.say(text, meta)

    async def say_line(
        self, line_id: str, *, gesture: str = "none", expression: Expression = "idle", **values: str
    ) -> None:
        if self._blocked(line_id):
            return
        await self._ctx.say_line(
            line_id, gesture=self._gesture(gesture), expression=expression, **values
        )

    # --- listening -----------------------------------------------------------------------------

    async def listen(
        self,
        silence_s: float | None,
        *,
        eyes: EyeState | None = "listening",
        clarify: bool = True,
        allow_empty: bool = False,
    ) -> Heard | None:
        speak_allowed = clarify and not self._silences
        answer = await conversation.listen(
            self._ctx,
            silence_s=silence_s,
            reprompt=False,
            clarify=speak_allowed,
            eyes=eyes,
            thinking=speak_allowed,
            allow_empty=allow_empty,
        )
        if isinstance(answer, conversation.Heard):
            return Heard(answer.text, typed=answer.typed)
        if answer.reason == "unclear":
            return Heard("", understood=False)
        return None

    # --- the body ------------------------------------------------------------------------------

    def _resolve(self, motion: str) -> str | None:
        body = self._ctx.bodies.active_name
        resolved = self._ctx.games.motions.resolve(motion, body)
        if resolved is None:
            self._ctx.log(
                "motion_skipped",
                {"motion": motion, "body": body, "reason": "not in motions.yaml for this body"},
            )
        return resolved

    def _gesture(self, gesture: str) -> str:
        return "none" if gesture == "none" else (self._resolve(gesture) or "none")

    async def play_motion(self, name: str) -> bool:
        resolved = self._resolve(name)
        if resolved is None:
            return False
        return (await self._ctx.bodies.play_motion(resolved)).ok

    async def set_eyes(self, state: EyeState) -> bool:
        return (await self._ctx.bodies.set_eyes(state)).ok

    async def rest(self) -> None:
        await self.play_motion("idle")
        await self.set_eyes("idle")

    # --- time, pause, WoZ ----------------------------------------------------------------------

    async def wait(self, seconds: float) -> None:
        await self._ctx.wait(seconds)

    async def wait_paused(self) -> None:
        await self._ctx.pause.wait_paused()

    async def wait_running(self) -> None:
        await self._ctx.pause.wait_running()

    async def woz_motion(self, names: Collection[str]) -> str:
        return await self._ctx.woz_signals.wait(names)

    # --- LLM, log, memory ----------------------------------------------------------------------

    async def ask_json(
        self, messages: Sequence[ChatMessage], parse: Callable[[str], T], *, purpose: str
    ) -> T | None:
        result = await self._ctx.dialogue.ask(
            messages, parse, timeout_s=self.config.llm_timeout_s, retries=self.config.llm_retries
        )
        for attempt, error in enumerate(result.errors, start=1):
            self._ctx.log(
                "llm_error",
                {
                    "error": error,
                    "attempt": attempt,
                    "retry": attempt < result.attempts,
                    "fallback": result.value is None and attempt == len(result.errors),
                    "purpose": purpose,
                },
            )
        return result.value

    def log(self, event_type: str, data: Mapping[str, Any]) -> None:
        self._ctx.log(event_type, dict(data))

    def remember(self, game: str, summary: str) -> None:
        memory = self._ctx.state.memory.add_game_event(game, summary)
        self._ctx.set_memory(memory, ["game_events"])

    def note(self, text: str) -> None:
        self._ctx.emit(f"  [game] {text}")
