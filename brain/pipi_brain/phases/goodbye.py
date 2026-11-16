"""ROBOT_GOODBYE and RETURN: the two memory references that close the break.

ROBOT_GOODBYE (robot): one concrete moment of the break + "back to your text", signature wave.
RETURN (pet): a *different* break detail + "finish your questions", then Pipi goes quiet and
only answers if spoken to, until ``session.return_end_s`` (null = the WoZ ends the session).

Game moments (``memory.game_events``, written by the games): the goodbye gets the latest one,
RETURN a different one. The LLM is told which moment to use (and, in RETURN, what the goodbye
already said); if the LLM fails, the fixed fallback lines carry the moment themselves.
With ``cues.memory_references: false`` no moment is mentioned.
"""

from __future__ import annotations

from pipi_brain.memory import Memory
from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen, reply

GOODBYE_EVENT = "<event: the break is over; say goodbye and that you are going back>"
RETURN_EVENT = "<event: you just landed back on the screen>"


def _break_details(memory: Memory) -> list[str]:
    details = []
    if memory.game_events:
        details.append("game_events")
    if memory.interests:
        details.append("interests")
    if memory.notable_quotes:
        details.append("notable_quotes")
    return details


def game_moments(memory: Memory) -> tuple[str | None, str | None]:
    """(for the goodbye, for RETURN): the latest game moment and a different one."""
    moments = list(dict.fromkeys(event.summary for event in memory.game_events))
    if not moments:
        return None, None
    return moments[-1], (moments[0] if len(moments) > 1 else None)


async def run_goodbye(ctx: PhaseContext) -> Next:
    gesture = "signature_wave" if ctx.app.cues.signature_gesture else "wave"
    moment = game_moments(ctx.state.memory)[0] if ctx.app.cues.memory_references else None
    turn = await reply(
        ctx,
        GOODBYE_EVENT,
        fallback_line="robot_goodbye_game" if moment else "robot_goodbye",
        fallback_values={"moment": moment} if moment else None,
        extra_instruction=(
            f'A game moment from this break to mention, in your own words: "{moment}"'
            if moment
            else None
        ),
        gesture=gesture,
    )
    ctx.state.goodbye_said = turn.say
    if ctx.app.cues.memory_references:
        ctx.memory_reference(_break_details(ctx.state.memory)[:1])
    return Next("MIGRATE_IN")


def _return_instruction(ctx: PhaseContext, moment: str | None) -> str | None:
    notes = []
    if ctx.state.goodbye_said:
        notes.append(
            f'When you left your robot body you said: "{ctx.state.goodbye_said}" '
            "Recall a DIFFERENT detail now."
        )
    if moment:
        notes.append(f'Another game moment you can mention, in your own words: "{moment}"')
    return "\n".join(notes) or None


async def run_return(ctx: PhaseContext) -> Next:
    moment = game_moments(ctx.state.memory)[1] if ctx.app.cues.memory_references else None
    await reply(
        ctx,
        RETURN_EVENT,
        fallback_line="return_fallback_game" if moment else "return_fallback",
        fallback_values={"moment": moment} if moment else None,
        extra_instruction=_return_instruction(ctx, moment),
    )
    if ctx.app.cues.memory_references:
        ctx.memory_reference(_break_details(ctx.state.memory)[:2][-1:])
    end_s = ctx.session.return_end_s
    if end_s is None:
        await _quietly_available(ctx)  # runs until the WoZ ends the session
    timer = ctx.countdown("return", end_s or 0.0)
    await ctx.until(timer, lambda: _quietly_available(ctx))
    return Next("END", "timer")


async def _quietly_available(ctx: PhaseContext) -> None:
    while True:
        heard = await listen(ctx, silence_s=None, reprompt=False)
        if isinstance(heard, Heard):
            await reply(ctx, heard.text, heard=heard)
