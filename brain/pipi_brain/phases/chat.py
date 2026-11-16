"""CHAT: short talk about the participant's interest (max N exchanges or ``chat_max_s``).

The robot opens with something it remembers (an identity cue, logged as
``memory_reference``), reacts with a gesture each turn, then: "Okay, I have a challenge for
you!" -> GAME_CROCODILE (demo mode, ``session.first_game: null``: straight to GAME_MENU).
"""

from __future__ import annotations

from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen, reply
from pipi_brain.protocol import Phase

OPENER_EVENT = "<event: the break just started; open the chat with something you remember>"


async def run(ctx: PhaseContext) -> Next:
    timer = ctx.countdown("chat", ctx.session.chat_max_s)
    finished = await ctx.until(timer, lambda: _chat(ctx))
    await ctx.say_line("chat_transition", gesture="excited", expression="determined")
    first_stop: Phase = "GAME_MENU" if ctx.session.first_game is None else "GAME_CROCODILE"
    return Next(first_stop, "auto" if finished else "timer")


async def _chat(ctx: PhaseContext) -> bool:
    memory = ctx.state.memory
    referenced = [
        field
        for field, known in (("interests", bool(memory.interests)), ("name", bool(memory.name)))
        if known and ctx.app.cues.memory_references
    ]
    await reply(ctx, OPENER_EVENT)
    ctx.memory_reference(referenced)
    for _ in range(ctx.session.chat_max_exchanges):
        heard = await listen(ctx, silence_s=ctx.app.timers.silence_reprompt_s, reprompt=True)
        if not isinstance(heard, Heard):
            return True
        await reply(ctx, heard.text, heard=heard)
    return True
