"""The game framework's contracts (docs/GAMES.md §1): ``Game``, ``GameContext``, results.

In plain words:
- A ``Game`` is a small class: it explains its rules, plays one round at a time and can
  switch to a simpler variant (``fallback_mode``) when something it needs is missing.
- A ``GameContext`` is everything the session lends a game: speaking and listening, the
  active body (motions, eyes), the LLM, memory, the log, the config, a clock and a random
  generator. Tests pass a fake context, so every game runs without hardware or network.
- ``games/runner.py`` drives a game: rules, rounds, the "again / stop / another game"
  question between rounds, the ``game_round`` log events and ``memory.game_events``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol, TypeVar

from pipi_brain.games.config import GamesConfig
from pipi_brain.memory import Memory
from pipi_brain.protocol import Expression, EyeState
from pipi_brain.speech.bang import BangDetector
from pipi_brain.vision.base import BlinkDetector

T = TypeVar("T")
ChatMessage = dict[str, str]
Winner = Literal["participant", "robot"]
OutcomeResult = Literal["completed", "stopped", "another_game", "unavailable", "aborted"]


@dataclass(frozen=True)
class GameInfo:
    """What the menu and the keyword fallback need to know about a game."""

    id: str  # "crocodile_robot", "quick_draw", ...
    display_name: str  # "the quick-draw duel"
    synonyms: tuple[str, ...]  # matched as words in what the participant said
    requires: frozenset[str] = field(default_factory=frozenset)  # e.g. {"camera"}
    menu_phrase: str = ""  # how the menu offers it: "a duel"
    description: str = ""  # one line for the LLM intent parser

    @property
    def phrase(self) -> str:
        return self.menu_phrase or self.display_name


@dataclass(frozen=True)
class Heard:
    """One thing the participant said (or typed) while a game listened."""

    text: str  # "" when speech was heard but not understood
    typed: bool = False
    understood: bool = True


@dataclass(frozen=True)
class RoundResult:
    result: str  # "guessed", "revealed", "participant_won", "robot_won", ...
    inputs: Mapping[str, Any] = field(default_factory=dict)  # what the participant did
    timings: Mapping[str, Any] = field(default_factory=dict)  # milliseconds
    winner: Winner | None = None
    fallback: str | None = None  # simpler variant used in this round, e.g. "slow_motion"
    memory: str | None = None  # a moment worth remembering, as Pipi would say it to "you"
    abort: bool = False  # the game cannot go on (e.g. the body does not move)


@dataclass(frozen=True)
class GameOutcome:
    """How a whole game ended (returned by ``runner.run_game``)."""

    game: str
    result: OutcomeResult
    rounds: int = 0
    fallback: str | None = None
    next_game: str | None = None  # "another game" and the participant already named one


class GameContext(Protocol):
    """What a game may use. Real: ``phases/game_context.py``; tests: a fake."""

    rng: random.Random
    config: GamesConfig

    @property
    def mode(self) -> str: ...  # "dev" | "study" | "demo"

    @property
    def capabilities(self) -> frozenset[str]: ...  # e.g. {"motions", "bang_detector"}

    @property
    def input_mode(self) -> Literal["voice", "typed"]: ...

    @property
    def hearing(self) -> bool: ...  # the participant is in the middle of speaking

    @property
    def bang_detector(self) -> BangDetector | None: ...

    @property
    def blink_detector(self) -> BlinkDetector | None: ...  # staring contest; None = pretend

    @property
    def memory(self) -> Memory: ...

    @property
    def halted(self) -> bool: ...  # emergency stop: send nothing more to the bodies

    def now(self) -> float:
        """Session clock, seconds (virtual time in tests)."""
        ...

    async def say(
        self, text: str, *, gesture: str = "none", expression: Expression = "idle"
    ) -> None: ...

    async def say_line(
        self, line_id: str, *, gesture: str = "none", expression: Expression = "idle", **values: str
    ) -> None: ...

    def silence(self, reason: str) -> AbstractContextManager[None]:
        """While active, ``say`` / ``say_line`` are blocked (nothing is spoken) and logged."""
        ...

    async def listen(
        self,
        silence_s: float | None,
        *,
        eyes: EyeState | None = "listening",
        clarify: bool = True,
        allow_empty: bool = False,
    ) -> Heard | None:
        """Wait for the participant; None after ``silence_s`` of silence. ``clarify=False``:
        never speak ("say that again?"), return ``Heard(understood=False)`` instead.
        ``allow_empty=True``: in a typed session just Enter counts too (the duel's bang)."""
        ...

    async def play_motion(self, name: str) -> bool:
        """Play a canonical motion (motions.yaml) on the active body; False = not played."""
        ...

    def can_play_motion(self, name: str) -> bool:
        """True if the active body has this canonical motion (motions.yaml); nothing is sent."""
        ...

    async def set_eyes(self, state: EyeState) -> bool: ...

    async def rest(self) -> None:
        """Back to the resting pose and idle eyes (ends a held motion such as ``act_bird``)."""
        ...

    async def wait(self, seconds: float) -> None:
        """Pausable wait (WoZ pause freezes it)."""
        ...

    async def wait_paused(self) -> None: ...

    async def wait_running(self) -> None: ...

    async def woz_motion(self, names: Collection[str]) -> str:
        """Wait until the experimenter plays one of these motions with WoZ ``play_motion``."""
        ...

    async def ask_json(
        self, messages: Sequence[ChatMessage], parse: Callable[[str], T], *, purpose: str
    ) -> T | None:
        """One LLM call with timeout; None when it failed or the answer was invalid (logged)."""
        ...

    def log(self, event_type: str, data: Mapping[str, Any]) -> None: ...

    def remember(self, game: str, summary: str) -> None:
        """Add a moment to ``memory.game_events`` (for the goodbye and RETURN lines)."""
        ...

    def note(self, text: str) -> None:
        """A short status line in the brain terminal (for the experimenter)."""
        ...


class Game(ABC):
    """One game. Instances live for a whole session (e.g. to avoid repeating words)."""

    info: ClassVar[GameInfo]
    has_fallback: ClassVar[bool] = False  # can run without its ``requires`` (simpler variant)
    max_rounds: int = 1

    @property
    def id(self) -> str:
        return self.info.id

    @property
    def display_name(self) -> str:
        return self.info.display_name

    @property
    def synonyms(self) -> tuple[str, ...]:
        return self.info.synonyms

    @property
    def requires(self) -> frozenset[str]:
        return self.info.requires

    @property
    def variant(self) -> str:
        """Which variant is being played (logged as ``mode``), e.g. "detector", "typed"."""
        return "normal"

    def motions(self) -> frozenset[str]:
        """Every canonical motion this game may play (checked against motions.yaml at start)."""
        return frozenset()

    def can_play(self) -> bool:
        """False when the game has nothing left to offer (e.g. no unused words)."""
        return True

    def rounds(self, mode: str) -> int:
        """How many rounds one game lasts in this mode (dev / study / demo)."""
        return self.max_rounds

    def start(self, ctx: GameContext) -> None:  # noqa: B027 - optional hook
        """Reset what belongs to one game (scores); called before ``explain``."""

    def progress(self) -> Mapping[str, Any]:
        """What happened so far in the running round (logged when the WoZ cuts it short)."""
        return {}

    @abstractmethod
    async def explain(self, ctx: GameContext) -> None:
        """Say the short, pre-written rules."""

    @abstractmethod
    async def play_round(self, ctx: GameContext, round_no: int) -> RoundResult:
        """Play one round and react to its result."""

    async def fallback_mode(self, ctx: GameContext) -> bool:
        """Switch to a simpler variant because a requirement failed; False = impossible."""
        return False

    def finished(self, results: Sequence[RoundResult]) -> bool:
        """True when the game is decided before all rounds are played (best of 3)."""
        return False

    async def finish(self, ctx: GameContext, results: Sequence[RoundResult]) -> str | None:
        """Final words after the last round; returns a summary for memory (or None)."""
        return None
