"""The interface every game implements (docs/GAMES.md §1). Games themselves come in M4/M6.

A game gets a ``GameContext`` (what the session lends it: speech, listening, the active body,
memory, logging) and returns a ``GameResult``. The session phases (GAME_CROCODILE,
GAME_CHOSEN) log ``game_start`` / ``game_end`` and write the result into memory, so the
goodbye and RETURN lines can mention it. Games log their own ``game_round`` events.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pipi_brain.protocol import EyeState


@dataclass(frozen=True)
class GameInfo:
    """What the menu and the keyword fallback need to know about a game."""

    id: str  # "crocodile_robot", "quick_draw", ...
    display_name: str
    synonyms: tuple[str, ...]  # matched as words in what the participant said
    requires: frozenset[str] = field(default_factory=frozenset)  # e.g. {"camera"}


@dataclass(frozen=True)
class GameResult:
    game: str
    summary: str  # one short sentence for memory ("guessed 'bird' on the first try")
    rounds: int = 0
    outcome: str = "played"  # e.g. "robot_won", "participant_won", "stopped"
    fallback: str | None = None  # e.g. "pretend" mode


class GameContext(Protocol):
    """What a game may use. M4 extends this (listening for guesses, bang detector, ...)."""

    async def say(self, text: str, *, gesture: str = "none") -> None: ...

    async def say_line(self, line_id: str, **values: str) -> None: ...

    async def play_motion(self, name: str) -> None: ...

    async def set_eyes(self, state: EyeState) -> None: ...

    def log(self, event_type: str, data: Mapping[str, Any]) -> None: ...


class Game(Protocol):
    info: GameInfo
    max_rounds: int

    async def play(self, ctx: GameContext) -> GameResult:
        """Explain, play the rounds, react; return the result (never raise)."""
        ...
