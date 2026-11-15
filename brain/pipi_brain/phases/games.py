"""GAME_CROCODILE, GAME_MENU, GAME_CHOSEN.

>>> M3 PLACEHOLDERS <<<  The real games come in M4 (docs/GAMES.md). Until then:
- a game phase says a short scripted line and waits ``session.game_placeholder_s``
  (WoZ ``end_game`` / ``next_phase`` ends it earlier); ``game_start`` / ``game_end`` are
  logged with ``placeholder: true``. A game registered in ``GameRegistry`` replaces the
  placeholder automatically (``Game.play``) - that is the M4 hook.
- GAME_MENU asks the menu question and understands the game by keyword (docs/GAMES.md §4
  keyword fallback). TODO(M4): LLM intent parser first, keywords as the fallback.

Flow: crocodile -> menu -> chosen game -> goodbye (``session.game_loop``: back to the menu).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen
from pipi_brain.phases.flow import successor
from pipi_brain.phases.voice import SayMeta
from pipi_brain.protocol import EyeState

CROCODILE = "crocodile_robot"


class SessionGameContext:
    """What a game may use (games/base.py ``GameContext``), backed by the session."""

    def __init__(self, ctx: PhaseContext) -> None:
        self._ctx = ctx

    async def say(self, text: str, *, gesture: str = "none") -> None:
        await self._ctx.voice.say(text, SayMeta(gesture=gesture))

    async def say_line(self, line_id: str, **values: str) -> None:
        await self._ctx.say_line(line_id, **values)

    async def play_motion(self, name: str) -> None:
        await self._ctx.bodies.play_motion(name)

    async def set_eyes(self, state: EyeState) -> None:
        await self._ctx.bodies.set_eyes(state)

    def log(self, event_type: str, data: Mapping[str, Any]) -> None:
        self._ctx.log(event_type, dict(data))


async def run_crocodile(ctx: PhaseContext) -> Next:
    await _play(ctx, CROCODILE, placeholder_line="game_crocodile_placeholder")
    return Next("GAME_MENU")


async def run_chosen(ctx: PhaseContext) -> Next:
    game = ctx.state.chosen_game or ctx.session.default_game
    info = ctx.registry.info(game)
    name = info.display_name if info is not None else game.replace("_", " ")
    await _play(ctx, game, placeholder_line="game_placeholder", game_name=name)
    ctx.state.chosen_game = None
    nxt = successor("GAME_CHOSEN", game_loop=ctx.session.game_loop)
    return Next(nxt or "ROBOT_GOODBYE")


async def run_menu(ctx: PhaseContext) -> Next:
    await ctx.say_line("game_menu", gesture="think")
    timer = ctx.countdown("game_menu", ctx.session.game_menu_s)
    choice = await ctx.until(timer, lambda: _ask_game(ctx))
    if choice == "stop":
        return Next("ROBOT_GOODBYE", "user")
    if choice is None:
        game = ctx.session.default_game
        ctx.log("game_choice", {"heard": None, "game": game, "method": "default"})
        await ctx.say_line("game_choice_default", gesture="excited")
        ctx.state.chosen_game = game
        return Next("GAME_CHOSEN", "timer")
    ctx.state.chosen_game = choice
    return Next("GAME_CHOSEN")


async def _ask_game(ctx: PhaseContext) -> str | None:
    """A game id, "stop", or None (no clear choice after one clarifying question)."""
    clarified = False
    while True:
        heard = await listen(ctx, silence_s=ctx.session.game_menu_s, reprompt=False)
        text = heard.text if isinstance(heard, Heard) else None
        if text is not None and ctx.registry.wants_stop(text):
            ctx.log(
                "game_choice",
                {"heard": text, "game": None, "action": "stop", "method": "keyword"},
            )
            return "stop"
        game = ctx.registry.match_keyword(text) if text is not None else None
        if game is not None:
            ctx.log("game_choice", {"heard": text, "game": game, "method": "keyword"})
            return game
        if clarified or text is None:
            return None
        clarified = True
        ctx.log("clarification", {"reason": "unclear_intent"})
        await ctx.say_line("game_menu_clarify")


async def _play(
    ctx: PhaseContext, game: str, *, placeholder_line: str, game_name: str = ""
) -> None:
    implementation = ctx.registry.implementation(game)
    start = time.perf_counter()
    ctx.log("game_start", {"game": game, "placeholder": implementation is None})
    result_text = "interrupted"  # e.g. WoZ end_game / next_phase
    try:
        if implementation is not None:
            result = await implementation.play(SessionGameContext(ctx))
            ctx.set_memory(ctx.state.memory.add_game_event(game, result.summary), ["game_events"])
            result_text = result.outcome
        else:
            await ctx.say_line(placeholder_line, gesture="excited", game=game_name or game)
            await ctx.wait(ctx.session.game_placeholder_s)
            result_text = "placeholder"
    finally:
        ctx.log(
            "game_end",
            {
                "game": game,
                "placeholder": implementation is None,
                "result": result_text,
                "duration_ms": round((time.perf_counter() - start) * 1000),
            },
        )
