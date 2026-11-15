"""Which games exist, which are implemented, and the keyword fallback of the game menu.

M3: all five games are *known* (names, synonyms) but none is implemented yet, so the session
plays a clearly marked placeholder instead. M4 registers real games with ``register``.
Keyword map from docs/GAMES.md §4 (used when the LLM intent parser fails or is not built yet).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from pipi_brain.games.base import Game, GameInfo

KNOWN_GAMES: tuple[GameInfo, ...] = (
    GameInfo(
        "crocodile_robot",
        "Crocodile",
        ("act", "acting", "charades", "crocodile", "guess", "pantomime"),
    ),
    GameInfo("quick_draw", "the quick-draw duel", ("duel", "cowboy", "bang", "draw", "shoot")),
    GameInfo(
        "staring",
        "the staring contest",
        ("stare", "staring", "blink", "blinking", "eyes"),
        frozenset({"camera"}),
    ),
    GameInfo(
        "rps_arms",
        "rock-paper-scissors",
        ("rock", "paper", "scissor", "scissors", "rps"),
        frozenset({"camera"}),
    ),
    GameInfo(
        "crocodile_human",
        "you act, I guess",
        ("my turn", "i act", "i'll act", "you guess", "i show"),
        frozenset({"camera"}),
    ),
)

STOP_WORDS: tuple[str, ...] = (
    "stop",
    "no more",
    "done",
    "enough",
    "finished",
    "nothing",
    "no thanks",
    "back to reading",
)


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


class GameRegistry:
    def __init__(self, known: tuple[GameInfo, ...] = KNOWN_GAMES) -> None:
        self._known: dict[str, GameInfo] = {info.id: info for info in known}
        self._games: dict[str, Game] = {}

    @property
    def known(self) -> Mapping[str, GameInfo]:
        return MappingProxyType(self._known)

    def info(self, game_id: str) -> GameInfo | None:
        return self._known.get(game_id)

    def register(self, game: Game) -> None:
        """M4: plug in a real game (it replaces the placeholder for its id)."""
        self._known[game.info.id] = game.info
        self._games[game.info.id] = game

    def implementation(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def match_keyword(self, text: str) -> str | None:
        """Game id mentioned in ``text`` (most specific match first), or None."""
        lowered = text.casefold()
        # "I act" / "my turn" means crocodile_human, even though "act" is a crocodile word.
        ordered = sorted(self._known.values(), key=lambda info: info.id != "crocodile_human")
        for info in ordered:
            if any(_contains(lowered, word) for word in info.synonyms):
                return info.id
        return None

    @staticmethod
    def wants_stop(text: str) -> bool:
        lowered = text.casefold()
        return any(_contains(lowered, word) for word in STOP_WORDS)
