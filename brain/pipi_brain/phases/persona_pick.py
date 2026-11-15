"""PERSONA_PICK: the participant chooses Pipi's personality (docs/INTERACTION_FLOW.md §2).

Pipi has already appeared on the screen (the controller makes the pet ``jump_in`` before the
first pet phase). Voice choice by keyword (id, label or a synonym from personas.yaml);
timeout -> ``persona.default``. ``persona.allow_choice: false`` skips the question.

TODO(M3+/pet): the pet's persona cards (``persona_picker`` message + ``user_click``) are not
in the protocol yet; when they are, a click resolves the choice here with method "click".
"""

from __future__ import annotations

import re

from pipi_brain.dialogue.content import Persona
from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen


def match_persona(text: str, personas: dict[str, Persona]) -> str | None:
    """Persona id mentioned in ``text`` (first match in the order of personas.yaml)."""
    lowered = text.casefold()
    for persona_id, persona in personas.items():
        words = {persona_id, persona.label.casefold(), *(w.casefold() for w in persona.synonyms)}
        if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in words):
            return persona_id
    return None


def _choose(ctx: PhaseContext, persona_id: str, method: str) -> None:
    ctx.log("persona_choice", {"persona": persona_id, "method": method})
    ctx.set_memory(ctx.state.memory.with_persona(persona_id), ["persona"])


async def run(ctx: PhaseContext) -> Next:
    default = ctx.app.persona.default
    if not ctx.app.persona.allow_choice:
        _choose(ctx, default, "config_fixed")
        return Next("GREETING")
    await ctx.say_line("persona_intro", gesture="wave", expression="happy")
    timer = ctx.countdown("persona_pick", ctx.session.persona_pick_s)
    chosen = await ctx.until(timer, lambda: _ask(ctx))
    if chosen is None:
        _choose(ctx, default, "timeout")
        await ctx.say_line("persona_default", expression="happy")
        return Next("GREETING", "timer")
    _choose(ctx, chosen, "voice")
    await ctx.say_line("persona_chosen", expression="happy", gesture="nod")
    return Next("GREETING")


async def _ask(ctx: PhaseContext) -> str:
    """Listen until a persona is recognised (the countdown above ends it otherwise)."""
    personas = dict(ctx.content.personas)
    asked_again = False
    while True:
        heard = await listen(ctx, silence_s=None, reprompt=False)
        if not isinstance(heard, Heard):
            continue
        chosen = match_persona(heard.text, personas)
        if chosen is not None:
            return chosen
        ctx.log("clarification", {"reason": "unclear_persona"})
        if not asked_again:
            asked_again = True
            await ctx.say_line("persona_unclear", start=heard.start, stt_ms=heard.stt_ms)
