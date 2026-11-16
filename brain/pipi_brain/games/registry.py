"""Which games exist, which are built, which can be played right now (docs/GAMES.md §1, §4).

- ``KNOWN_GAMES``: all five games of the design (names, synonyms). Only what is *registered*
  is really built: M4 registers ``crocodile_robot`` and ``quick_draw`` (``games/setup.py``).
  ``staring``, ``rps_arms`` and ``crocodile_human`` come in M6; until then they are known
  (Pipi understands "the blinking game" and says it cannot play it yet) but never offered.
- ``available(capabilities)``: the registered games whose requirements are met right now, or
  that have a fallback variant. Everything else is hidden from the menu.
- ``match_keyword``: the keyword fallback map of the game menu (used when the LLM fails).
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
        ("act", "acting", "charades", "crocodile", "guess", "guessing", "pantomime"),
        frozenset({"motions", "acting_motions"}),
        menu_phrase="Crocodile",
        description="Pipi acts something out without talking and the participant guesses",
    ),
    GameInfo(
        "quick_draw",
        "the quick-draw duel",
        ("duel", "cowboy", "bang", "draw", "shoot", "shooting"),
        frozenset({"bang_detector"}),
        menu_phrase="a duel",
        description="a reaction duel: shout BANG when Pipi's eyes turn green",
    ),
    GameInfo(
        "staring",
        "the staring contest",
        ("stare", "staring", "blink", "blinking", "eyes"),
        frozenset({"camera"}),
        menu_phrase="a staring contest",
        description="the first one to blink loses",
    ),
    GameInfo(
        "rps_arms",
        "rock-paper-scissors",
        ("rock", "paper", "scissor", "scissors", "rps"),
        frozenset({"camera"}),
        menu_phrase="rock-paper-scissors",
        description="rock-paper-scissors shown with the arms",
    ),
    GameInfo(
        "crocodile_human",
        "you act, I guess",
        ("my turn", "i act", "i'll act", "you guess", "i show"),
        frozenset({"camera"}),
        menu_phrase="you act and I guess",
        description="the participant acts something out and Pipi guesses",
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


def game_info(game_id: str) -> GameInfo:
    """The catalogue entry of a known game (KeyError for an unknown id)."""
    return next(info for info in KNOWN_GAMES if info.id == game_id)


def contains_phrase(text: str, phrase: str) -> bool:
    """True if ``phrase`` appears in ``text`` as whole words (both compared in lower case)."""
    return re.search(rf"\b{re.escape(phrase.casefold())}\b", text.casefold()) is not None


class GameRegistry:
    def __init__(self, known: tuple[GameInfo, ...] = KNOWN_GAMES) -> None:
        self._known: dict[str, GameInfo] = {info.id: info for info in known}
        self._games: dict[str, Game] = {}

    @property
    def known(self) -> Mapping[str, GameInfo]:
        return MappingProxyType(self._known)

    @property
    def registered(self) -> tuple[Game, ...]:
        return tuple(self._games.values())

    def info(self, game_id: str) -> GameInfo | None:
        return self._known.get(game_id)

    def register(self, game: Game) -> None:
        """Plug in a built game (it replaces the placeholder of its id)."""
        self._known[game.info.id] = game.info
        self._games[game.info.id] = game

    def implementation(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def playable(self, game: Game, capabilities: frozenset[str]) -> bool:
        """Requirements met (or a fallback variant exists) and the game has something left."""
        return game.can_play() and (game.requires <= capabilities or game.has_fallback)

    def available(self, capabilities: frozenset[str]) -> tuple[Game, ...]:
        """The games the menu may offer right now, in registration order."""
        return tuple(game for game in self._games.values() if self.playable(game, capabilities))

    def match_keyword(self, text: str) -> str | None:
        """Game id mentioned in ``text`` (most specific match first), or None."""
        # "I act" / "my turn" means crocodile_human, even though "act" is a crocodile word.
        ordered = sorted(self._known.values(), key=lambda info: info.id != "crocodile_human")
        for info in ordered:
            if any(contains_phrase(text, word) for word in info.synonyms):
                return info.id
        return None

    @staticmethod
    def wants_stop(text: str) -> bool:
        return any(contains_phrase(text, word) for word in STOP_WORDS)
