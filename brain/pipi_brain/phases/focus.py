"""FOCUS: the fixed reading timer. Pipi is quiet and only answers when spoken to.

- Calm mode on the pet for the whole phase (``Calm(on=True)`` at the start, off at the end,
  also when the WoZ cuts the phase short).
- Word help: the LLM answers in <= 2 sentences and names the term (``help_term``) -> a
  ``word_help`` event and ``memory.word_help``.
- Soft pre-cue: a small yawn/stretch (no speech) when ``focus_s - focus_precue_s`` is left.
- Timer end -> MIGRATE_OUT. WoZ: ``extend_focus`` adds time, ``next_phase`` ends it early.
"""

from __future__ import annotations

import asyncio
import contextlib

from pipi_brain.phases.clock import cancel_and_wait
from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen, reply
from pipi_brain.phases.timers import Countdown

PRECUE_MOTION = "yawn"  # a pet clip (docs/SYSTEM_DESIGN.md §5); no speech


async def run(ctx: PhaseContext) -> Next:
    await ctx.bodies.set_calm(True)
    try:
        timers = ctx.app.timers
        # The fixed timer starts with the phase; WoZ time added before this point counts too.
        timer = ctx.countdown("focus", timers.focus_s + ctx.state.focus_extra_s)
        ctx.state.focus_extra_s = 0.0
        await ctx.say_line("focus_start", expression="happy")
        precue = asyncio.ensure_future(
            _precue(ctx, timer, lead_s=max(0, timers.focus_s - timers.focus_precue_s))
        )
        try:
            await ctx.until(timer, lambda: _answer_questions(ctx))
        finally:
            await cancel_and_wait([precue])
        return Next("MIGRATE_OUT", "timer")
    finally:
        with contextlib.suppress(Exception):
            await asyncio.shield(ctx.bodies.set_calm(False))


async def _precue(ctx: PhaseContext, timer: Countdown, *, lead_s: float) -> None:
    await timer.wait_until_remaining(lead_s)
    if not timer.expired:
        ctx.log("focus_precue", {"motion": PRECUE_MOTION, "remaining_s": timer.remaining_s})
        await ctx.bodies.play_motion(PRECUE_MOTION)


async def _answer_questions(ctx: PhaseContext) -> None:
    extra = f"Reading text:\n{ctx.reading_text}" if ctx.reading_text else None
    while True:
        heard = await listen(ctx, silence_s=None, reprompt=False)
        if not isinstance(heard, Heard):
            continue
        turn = await reply(ctx, heard.text, heard=heard, extra_instruction=extra)
        if turn.help_term:
            ctx.log("word_help", {"term": turn.help_term, "answer": turn.say})
            memory = ctx.state.memory.add_word_help(
                turn.help_term, "FOCUS", round(ctx.clock.now() * 1000)
            )
            ctx.set_memory(memory, ["word_help"])
