"""GREETING: name -> free-time interest -> feeling about reading, stored in memory.

Scripted structure, LLM wording (prompts/greeting.txt). Ends when memory has all three, after
``session.greeting_max_turns`` answers, after ``session.greeting_max_s``, or when the
participant stays silent (one re-prompt first) -> FOCUS.
"""

from __future__ import annotations

from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen, reply
from pipi_brain.privacy import guess_name


async def run(ctx: PhaseContext) -> Next:
    await ctx.say_line("greeting_ask_name", expression="happy")
    timer = ctx.countdown("greeting", ctx.session.greeting_max_s)
    finished = await ctx.until(timer, lambda: _talk(ctx))
    return Next("FOCUS", "auto" if finished else "timer")


async def _talk(ctx: PhaseContext) -> bool:
    silence_s = ctx.app.timers.silence_reprompt_s
    for turn_no in range(ctx.session.greeting_max_turns):
        heard = await listen(ctx, silence_s=silence_s, reprompt=True)
        if not isinstance(heard, Heard):
            return True  # silent or not understood twice: start reading anyway
        await reply(ctx, heard.text, heard=heard)
        if ctx.state.memory.name is None:
            # The LLM did not pick the name out (e.g. it is down): still keep it out of the
            # log. Used for redaction only, never for Pipi's memory (privacy.py).
            ctx.events.logger.redact_name(guess_name(heard.text, first_answer=turn_no == 0))
        if ctx.state.memory.greeting_complete:
            return True
    return True
