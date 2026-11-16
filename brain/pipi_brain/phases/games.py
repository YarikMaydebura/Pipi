"""GAME_CROCODILE, GAME_MENU, GAME_CHOSEN (docs/INTERACTION_FLOW.md, docs/GAMES.md §4-5).

- GAME_CROCODILE plays the fixed first game (``session.first_game``; study: always
  ``crocodile_robot``). Demo mode has no fixed first game: straight to the menu.
- GAME_MENU: "What do you want to play next?" Only games that are built AND possible right
  now are offered. The answer goes to the LLM intent parser (keyword map as the fallback).
  One clarifying question; a second failure or silence -> the default game.
- GAME_CHOSEN runs the chosen game. Study mode: one chosen game, then the goodbye. Demo mode
  (``session.game_loop``): back to the menu until the participant says they are done.

The games themselves live in ``pipi_brain/games/`` and are driven by ``games/runner.py``.

Not built yet (M6): ``staring``, ``rps_arms``, ``crocodile_human``. They are known (Pipi
understands "the blinking game" and says it cannot play it yet) but never offered, and the
WoZ ``start_game`` refuses them with a clear error. There is no placeholder game any more.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pipi_brain.games.base import Game, GameInfo, GameOutcome
from pipi_brain.games.intent import understand, yes_or_no
from pipi_brain.games.runner import run_game
from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen
from pipi_brain.phases.flow import Trigger, successor
from pipi_brain.phases.game_context import SessionGameContext, capabilities
from pipi_brain.protocol import Phase

MAX_MENU_FAILURES = 2  # unclear answers before Pipi picks the default game
STOP = "stop"


def spoken_options(games: Sequence[GameInfo]) -> str:
    """["Crocodile", "a duel", "x"] -> "Crocodile, a duel or x" (for the menu lines)."""
    phrases = [info.phrase for info in games]
    if len(phrases) <= 1:
        return "".join(phrases)
    return f"{', '.join(phrases[:-1])} or {phrases[-1]}"


# --- GAME_CROCODILE / GAME_CHOSEN ----------------------------------------------------------------


async def run_crocodile(ctx: PhaseContext) -> Next:
    first = ctx.session.first_game
    if first is None:  # demo: any game first
        return Next("GAME_MENU")
    return _after_game(ctx, "GAME_CROCODILE", await _play(ctx, first))


async def run_chosen(ctx: PhaseContext) -> Next:
    game = ctx.state.chosen_game or ctx.session.default_game
    outcome = await _play(ctx, game)
    # Cleared only now: after an emergency stop, `resume` restarts this phase with the same game.
    ctx.state.chosen_game = None
    return _after_game(ctx, "GAME_CHOSEN", outcome)


def _after_game(ctx: PhaseContext, phase: Phase, outcome: GameOutcome | None) -> Next:
    """Where to go after a game: the participant's wish first, else the normal flow."""
    loop = ctx.session.game_loop
    if outcome is not None and outcome.result == "stopped":
        return Next("ROBOT_GOODBYE", "user")
    if outcome is not None and outcome.result == "another_game":
        if phase == "GAME_CHOSEN" and not loop:
            return Next("ROBOT_GOODBYE", "user")  # study: only one chosen game
        wanted = ctx.registry.implementation(outcome.next_game or "")
        if wanted is not None and ctx.registry.playable(wanted, capabilities(ctx)):
            ctx.state.chosen_game = wanted.id  # they already said which one: skip the menu
            return Next("GAME_CHOSEN", "user")
        return Next("GAME_MENU", "user")
    return Next(successor(phase, game_loop=loop) or "ROBOT_GOODBYE")


async def _play(ctx: PhaseContext, game_id: str) -> GameOutcome | None:
    """Run a built game. Unbuilt games never get here (menu, WoZ and config refuse them)."""
    game = ctx.registry.implementation(game_id)
    if game is None:
        ctx.log("game_start", {"game": game_id, "placeholder": False, "error": "not built"})
        ctx.log("game_end", {"game": game_id, "placeholder": False, "result": "unavailable"})
        ctx.events.alert("error", f"Game {game_id} is not built yet: skipped.")
        return None
    ctx.state.last_game = game_id
    return await run_game(game, SessionGameContext(ctx), registry=ctx.registry)


# --- GAME_MENU -----------------------------------------------------------------------------------


async def run_menu(ctx: PhaseContext) -> Next:
    game_ctx = SessionGameContext(ctx)
    available = ctx.registry.available(game_ctx.capabilities)
    if not available:
        _log_choice(ctx, None, None, "none_available")
        ctx.events.alert("warning", "No game can be played right now: Pipi says goodbye.")
        return Next("ROBOT_GOODBYE")
    options = spoken_options([game.info for game in available])
    question = "game_menu" if len(available) > 1 else "game_menu_one"
    await ctx.say_line(question, gesture="think", options=options)
    choice, trigger = await _ask_game(ctx, game_ctx, available, options)
    if choice == STOP:
        return Next("ROBOT_GOODBYE", "user")
    ctx.state.chosen_game = choice
    return Next("GAME_CHOSEN", trigger)


async def _ask_game(
    ctx: PhaseContext, game_ctx: SessionGameContext, available: Sequence[Game], options: str
) -> tuple[str, Trigger]:
    """(game id or STOP, why). Unclear twice or silent -> the default game."""
    infos = [game.info for game in available]
    offered = {info.id: info for info in infos}
    failures = 0
    listed = False
    heard_text: str | None = None
    while True:
        ctx.countdown("game_menu", ctx.session.game_menu_s)  # shown in the WoZ panel
        heard = await listen(ctx, silence_s=ctx.session.game_menu_s, reprompt=False)
        if not isinstance(heard, Heard):  # silent, or not understood twice
            return await _default_game(ctx, available, heard_text), "timer"
        heard_text = heard.text
        understood = await understand(
            game_ctx,
            heard.text,
            registry=ctx.registry,
            available=infos,
            last_game=ctx.state.last_game,
        )
        intent, method = understood.intent, understood.method
        if len(infos) == 1 and intent.action in ("unknown", "clarify"):
            answer = yes_or_no(heard.text, infos[0].id)  # "Do you want to play a duel?" - "yes"
            if answer is not None:
                intent, method = answer, "keyword"
        timing = {"start": heard.start, "stt_ms": heard.stt_ms}
        if intent.action == "stop":
            _log_choice(ctx, heard.text, None, method, action="stop")
            return STOP, "user"
        if intent.action == "start_game" and intent.game in offered:
            _log_choice(ctx, heard.text, intent.game, method)
            phrase = offered[intent.game].phrase
            await ctx.say_line("game_chosen", gesture="excited", game=phrase, **timing)
            return intent.game, "auto"
        if intent.action == "list_games" and not listed:
            listed = True  # answering "which games are there?" is not a failure
            await ctx.say_line("game_menu_list", options=options, **timing)
            continue
        failures += 1
        unavailable = intent.action == "start_game"  # a game Pipi knows but cannot play now
        if unavailable:
            _log_choice(ctx, heard.text, intent.game, method, available=False)
        else:
            ctx.log("clarification", {"reason": "unclear_intent"})
        if failures >= MAX_MENU_FAILURES:
            return await _default_game(ctx, available, heard_text), "auto"
        line = "game_unavailable" if unavailable else "game_menu_clarify"
        await ctx.say_line(line, options=options, **timing)


async def _default_game(ctx: PhaseContext, available: Sequence[Game], heard: str | None) -> str:
    """No clear choice: ``session.default_game`` (or the first game that can be played)."""
    by_id = {game.id: game for game in available}
    game = by_id.get(ctx.session.default_game, available[0])
    _log_choice(ctx, heard, game.id, "default")
    await ctx.say_line("game_choice_default", gesture="excited", game=game.info.phrase)
    return game.id


def _log_choice(
    ctx: PhaseContext, heard: str | None, game: str | None, method: str, **extra: Any
) -> None:
    ctx.log("game_choice", {"heard": heard, "game": game, "method": method, **extra})
