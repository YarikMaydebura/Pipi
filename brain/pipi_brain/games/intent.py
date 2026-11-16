"""Understanding what the participant wants to play (docs/GAMES.md §4).

Two questions are answered here:
- the game menu: "What do you want to play next?" -> ``understand`` asks the LLM for the
  intent JSON ``{"action", "game", "say"}`` (validated); if the LLM fails, or does not get it
  while a keyword clearly does, the keyword map decides (``keyword_intent``).
- between rounds: "again", "stop" or "another game"? -> ``between_rounds``. Keywords first
  (instant for "yes" / "stop"), the LLM only for anything else.

Everything except the two ``async`` functions is pure and unit-tested.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from pipi_brain.dialogue.schemas import parse_model
from pipi_brain.games.base import ChatMessage, GameContext, GameInfo
from pipi_brain.games.registry import KNOWN_GAMES, GameRegistry, contains_phrase

IntentAction = Literal["start_game", "list_games", "clarify", "stop", "unknown"]
RoundChoice = Literal["continue", "stop", "another_game"]
GAME_IDS: tuple[str, ...] = tuple(info.id for info in KNOWN_GAMES)
MAX_INTENT_SAY_CHARS = 200

AGAIN_WORDS = ("again", "same", "one more", "once more", "rematch", "another round")
LIST_WORDS = ("which games", "what games", "what can", "options", "choices", "list")
CONTINUE_WORDS = (
    *AGAIN_WORDS,
    "yes",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "next",
    "continue",
    "go on",
    "ready",
    "let's go",
)
SWITCH_WORDS = (
    "another game",
    "other game",
    "different game",
    "something else",
    "change game",
    "switch",
)


class GameIntent(BaseModel):
    """The validated intent JSON. ``say`` is optional and never spoken (fixed lines are)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    action: IntentAction
    game: str | None = None
    say: str = ""

    @model_validator(mode="before")
    @classmethod
    def _consistent(cls, data: Any) -> Any:
        """An unknown game id counts as no game; start_game without a game = clarify."""
        if not isinstance(data, dict):
            return data
        game = data.get("game") if data.get("game") in GAME_IDS else None
        action = data.get("action")
        if action == "start_game" and game is None:
            action = "clarify"
        return {**data, "action": action, "game": game if action == "start_game" else None}

    @field_validator("say", mode="before")
    @classmethod
    def _short_say(cls, value: Any) -> Any:
        return " ".join(value.split())[:MAX_INTENT_SAY_CHARS] if isinstance(value, str) else ""


def parse_game_intent(raw: str) -> GameIntent:
    """The model's text as a GameIntent, or raise InvalidModelOutput."""
    return parse_model(raw, GameIntent)


def _has_any(text: str, phrases: Sequence[str]) -> bool:
    return any(contains_phrase(text, phrase) for phrase in phrases)


def keyword_intent(text: str, registry: GameRegistry, *, last_game: str | None) -> GameIntent:
    """The keyword fallback map: stop words, "again", a game's synonyms, "which games?"."""
    if registry.wants_stop(text):
        return GameIntent(action="stop")
    game = registry.match_keyword(text)
    if game is not None:
        return GameIntent(action="start_game", game=game)
    if last_game is not None and _has_any(text, AGAIN_WORDS):
        return GameIntent(action="start_game", game=last_game)
    if _has_any(text, LIST_WORDS):
        return GameIntent(action="list_games")
    return GameIntent(action="unknown")


def yes_or_no(text: str, only_game: str) -> GameIntent | None:
    """Only one game can be played and Pipi asked "Want to play it?": yes / no by keyword."""
    if _has_any(text, CONTINUE_WORDS):  # first: "yes, no problem" is a yes
        return GameIntent(action="start_game", game=only_game)
    if _has_any(text, ("no", "nope", "not now", "rather not")):
        return GameIntent(action="stop")
    return None


def build_intent_messages(
    text: str,
    *,
    available: Sequence[GameInfo],
    unavailable: Sequence[GameInfo],
    last_game: str | None,
) -> list[ChatMessage]:
    """The prompt of the intent parser: the games, their synonyms and the JSON format."""

    def describe(info: GameInfo) -> str:
        return (
            f"- {info.id}: {info.display_name} ({info.description}); "
            f"also called: {', '.join(info.synonyms)}"
        )

    playable = "\n".join(describe(info) for info in available) or "- (none)"
    lines = [
        "You work out which game a participant wants to play with Pipi, a small robot "
        "study companion. The participant just answered: 'What do you want to play next?'",
        f"Games Pipi can play right now:\n{playable}",
    ]
    if unavailable:
        lines.append(
            "Games Pipi knows but cannot play right now (if they ask for one, still answer "
            "start_game with its id; Pipi will explain):\n"
            + "\n".join(describe(info) for info in unavailable)
        )
    if last_game is not None:
        lines.append(f'They just played: {last_game} ("again", "the same", "one more" mean it).')
    lines.append(
        "Return ONLY valid JSON (no markdown, no extra text):\n"
        '{"action": "start_game" | "list_games" | "clarify" | "stop" | "unknown", '
        f'"game": one of {list(GAME_IDS)} or null}}\n'
        "- start_game: they named or described a game. Synonyms and descriptions count "
        '("the cowboy one" = quick_draw, "the blinking game" = staring).\n'
        "- list_games: they ask which games there are.\n"
        "- stop: they want no more games, or to go back to reading.\n"
        "- clarify: they want to play, but it is not clear which game.\n"
        "- unknown: anything else."
    )
    return [
        {"role": "system", "content": "\n\n".join(lines)},
        {"role": "user", "content": text},
    ]


@dataclass(frozen=True)
class Understood:
    intent: GameIntent
    method: Literal["llm", "keyword"]


async def understand(
    ctx: GameContext,
    text: str,
    *,
    registry: GameRegistry,
    available: Sequence[GameInfo],
    last_game: str | None,
) -> Understood:
    """LLM intent first; the keyword map when the LLM fails or is unsure and a keyword is clear."""
    offered = {info.id for info in available}
    unavailable = [info for info in registry.known.values() if info.id not in offered]
    messages = build_intent_messages(
        text, available=available, unavailable=unavailable, last_game=last_game
    )
    from_llm = await ctx.ask_json(messages, parse_game_intent, purpose="game_intent")
    from_keywords = keyword_intent(text, registry, last_game=last_game)
    if from_llm is None:
        return Understood(from_keywords, "keyword")
    if from_llm.action in ("unknown", "clarify") and from_keywords.action in ("start_game", "stop"):
        return Understood(from_keywords, "keyword")
    return Understood(from_llm, "llm")


@dataclass(frozen=True)
class BetweenRounds:
    choice: RoundChoice
    method: Literal["keyword", "llm", "default"]
    game: str | None = None  # "another game" and they already said which one


def keyword_between(text: str, registry: GameRegistry, *, current: str) -> BetweenRounds | None:
    """A clear "stop" / "another game" / "again" by keyword; None = not clear."""
    if registry.wants_stop(text):
        return BetweenRounds("stop", "keyword")
    named = registry.match_keyword(text)
    other = named if named != current else None
    if _has_any(text, SWITCH_WORDS) or other is not None:
        return BetweenRounds("another_game", "keyword", other)
    if named == current or _has_any(text, CONTINUE_WORDS):
        return BetweenRounds("continue", "keyword")
    return None


async def between_rounds(
    ctx: GameContext,
    text: str,
    *,
    registry: GameRegistry,
    available: Sequence[GameInfo],
    current: str,
) -> BetweenRounds:
    """What the participant wants at a round boundary. Unclear -> the game simply continues."""
    by_keyword = keyword_between(text, registry, current=current)
    if by_keyword is not None:
        return by_keyword
    offered = {info.id for info in available}
    unavailable = [info for info in registry.known.values() if info.id not in offered]
    messages = build_intent_messages(
        text, available=available, unavailable=unavailable, last_game=current
    )
    intent = await ctx.ask_json(messages, parse_game_intent, purpose="game_intent")
    if intent is None:
        return BetweenRounds("continue", "default")
    if intent.action == "stop":
        return BetweenRounds("stop", "llm")
    if intent.action == "start_game" and intent.game != current:
        return BetweenRounds("another_game", "llm", intent.game)
    return BetweenRounds("continue", "llm")
