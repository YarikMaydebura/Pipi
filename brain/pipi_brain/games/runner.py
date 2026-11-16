"""Runs one game from the rules to the last round (docs/GAMES.md §1).

    requirements met? (else the game's fallback variant, else "I can't play that now")
    -> rules -> round 1 -> [listen: "stop" / "another game"? silence = go on] -> round 2 ...
    -> final words

What is logged: ``game_start``, one ``game_round`` per round (game, round, inputs, result,
timings, fallback used; also for a round that the WoZ cut short: result ``interrupted``),
``game_choice`` for what the participant said between rounds, and ``game_end``.
Moments worth remembering go to ``memory.game_events`` right after each round, so the robot
goodbye and the pet's RETURN line can mention them.

Stopping: a WoZ command (``end_game``, ``next_phase``, ``emergency_stop`` ...) cancels the
phase task; the cancellation passes through here, the logs are still written, the body is
sent back to its resting pose (acting motions are held until told otherwise), and nothing
keeps running in the background.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from typing import Any

from pipi_brain.games.base import Game, GameContext, GameOutcome, OutcomeResult, RoundResult
from pipi_brain.games.intent import BetweenRounds, between_rounds
from pipi_brain.games.registry import GameRegistry

CONTINUE = BetweenRounds("continue", "default")


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


async def run_game(game: Game, ctx: GameContext, *, registry: GameRegistry) -> GameOutcome:
    """Play ``game`` once. Cancelled by the WoZ / emergency stop: the logs are still written."""
    started = ctx.now()
    game.start(ctx)
    missing = sorted(game.requires - ctx.capabilities)
    playable = game.can_play() and (not missing or await game.fallback_mode(ctx))
    fallback = game.variant if missing and playable else None
    planned = game.rounds(ctx.mode) if playable else 0
    ctx.log(
        "game_start",
        {
            "game": game.id,
            "placeholder": False,
            "mode": game.variant,
            "rounds_planned": planned,
            "missing_requirements": missing,
            "fallback": fallback,
        },
    )
    results: list[RoundResult] = []
    result: str = "interrupted"  # stays like this when the WoZ ends the game
    next_game: str | None = None
    try:
        if not playable:
            result = "unavailable"
            await ctx.say_line("game_unavailable_now", expression="sad")
        else:
            result, next_game = await _play_rounds(game, ctx, registry, planned, results)
    except Exception:
        result = "error"  # a bug in a game: logged here, reported by the controller
        raise
    finally:
        ctx.log(
            "game_end",
            {
                "game": game.id,
                "placeholder": False,
                "result": result,
                "rounds": len(results),
                "mode": game.variant,
                "fallback": _fallback_used(fallback, results),
                "duration_ms": _ms(ctx.now() - started),
            },
        )
        if result in ("interrupted", "error") and not ctx.halted:
            # act_* and duel_ready are held by the body until the next motion: end them now.
            # (Not after an emergency stop: the bodies were stopped and must stay still.)
            with contextlib.suppress(Exception):
                await asyncio.shield(ctx.rest())
    outcome: OutcomeResult = result  # type: ignore[assignment]  # "interrupted" never gets here
    return GameOutcome(game.id, outcome, len(results), _fallback_used(fallback, results), next_game)


async def _play_rounds(
    game: Game,
    ctx: GameContext,
    registry: GameRegistry,
    planned: int,
    results: list[RoundResult],
) -> tuple[OutcomeResult, str | None]:
    await game.explain(ctx)
    for round_no in range(1, planned + 1):
        round_result = await _play_round(game, ctx, round_no)
        results.append(round_result)
        if round_result.memory:
            ctx.remember(game.id, round_result.memory)
        if round_result.abort:
            return "aborted", None
        if round_no == planned or game.finished(results):
            break
        wish = await _listen_between_rounds(game, ctx, registry, round_no)
        if wish.choice == "stop":
            await ctx.say_line("game_stop_ok", expression="happy")
            return "stopped", None
        if wish.choice == "another_game":
            await ctx.say_line("game_switch_ok", expression="happy")
            return "another_game", wish.game
    summary = await game.finish(ctx, results)
    if summary:
        ctx.remember(game.id, summary)
    return "completed", None


async def _play_round(game: Game, ctx: GameContext, round_no: int) -> RoundResult:
    started = ctx.now()
    try:
        result = await game.play_round(ctx, round_no)
    except asyncio.CancelledError:
        cut_short = RoundResult("interrupted", inputs=game.progress())
        _log_round(game, ctx, round_no, cut_short, ctx.now() - started)
        raise
    _log_round(game, ctx, round_no, result, ctx.now() - started)
    return result


def _log_round(
    game: Game, ctx: GameContext, round_no: int, result: RoundResult, duration_s: float
) -> None:
    data: dict[str, Any] = {
        "game": game.id,
        "round": round_no,
        "mode": game.variant,
        "result": result.result,
        "winner": result.winner,
        "inputs": dict(result.inputs),
        "timings": {**result.timings, "round_ms": _ms(duration_s)},
        "fallback": result.fallback,
    }
    ctx.log("game_round", data)


async def _listen_between_rounds(
    game: Game, ctx: GameContext, registry: GameRegistry, round_no: int
) -> BetweenRounds:
    """A short listening window: "stop" / "another game"; silence or "again" = next round."""
    window_s = ctx.config.between_rounds_s
    if window_s <= 0:
        return CONTINUE
    heard = await ctx.listen(window_s, clarify=False)
    if heard is None or not heard.understood or not heard.text.strip():
        return CONTINUE
    available = [other.info for other in registry.available(ctx.capabilities)]
    wish = await between_rounds(
        ctx, heard.text, registry=registry, available=available, current=game.id
    )
    ctx.log(
        "game_choice",
        {
            "heard": heard.text,
            "game": wish.game if wish.choice == "another_game" else game.id,
            "action": wish.choice,
            "method": wish.method,
            "context": "between_rounds",
            "after_round": round_no,
        },
    )
    return wish


def _fallback_used(start_fallback: str | None, results: Sequence[RoundResult]) -> str | None:
    """The fallback variant of the game: chosen at the start, or switched to in a round."""
    for round_result in reversed(results):
        if round_result.fallback:
            return round_result.fallback
    return start_fallback
