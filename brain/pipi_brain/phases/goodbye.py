"""ROBOT_GOODBYE and RETURN: the two memory references that close the break.

ROBOT_GOODBYE (robot): one concrete moment of the break + "back to your text", signature wave.
RETURN (pet): a *different* break detail + "finish your questions", then Pipi goes quiet and
only answers if spoken to, until ``session.return_end_s`` (null = the WoZ ends the session).
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


async def run_goodbye(ctx: PhaseContext) -> Next:
    gesture = "signature_wave" if ctx.app.cues.signature_gesture else "wave"
    await reply(ctx, GOODBYE_EVENT, fallback_line="robot_goodbye", gesture=gesture)
    if ctx.app.cues.memory_references:
        ctx.memory_reference(_break_details(ctx.state.memory)[:1])
    return Next("MIGRATE_IN")


async def run_return(ctx: PhaseContext) -> Next:
    await reply(ctx, RETURN_EVENT, fallback_line="return_fallback")
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
