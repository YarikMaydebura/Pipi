"""PERSONA_PICK: the participant chooses Pipi's personality (docs/INTERACTION_FLOW.md §2).

Pipi has already appeared on the screen (the controller makes the pet ``jump_in`` before the
first pet phase). The pet shows three persona cards (``persona_picker``); the participant
clicks one (``user_click`` "persona:<id>", method ``click``) or says it (keyword: id, label or
a synonym from personas.yaml, method ``voice``), whichever comes first. Timeout ->
``persona.default``. ``persona.allow_choice: false`` skips the question. The cards are hidden
when the phase ends in any way (also when the WoZ jumps elsewhere).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Callable

from pipi_brain.dialogue.content import Persona
from pipi_brain.phases.clock import first_of
from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.conversation import Heard, listen
from pipi_brain.protocol import PERSONA_CLICK_PREFIX, PersonaOption


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


def persona_options(personas: dict[str, Persona]) -> list[PersonaOption]:
    """The cards the pet shows, in the order of personas.yaml."""
    return [
        PersonaOption(id=persona_id, label=persona.label, description=persona.description)
        for persona_id, persona in personas.items()
    ]


async def run(ctx: PhaseContext) -> Next:
    default = ctx.app.persona.default
    if not ctx.app.persona.allow_choice:
        _choose(ctx, default, "config_fixed")
        return Next("GREETING")
    await ctx.say_line("persona_intro", gesture="wave", expression="happy")
    personas = dict(ctx.content.personas)
    # Listen for clicks BEFORE the cards appear: a quick click must not get lost.
    clicked: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    unsubscribe = ctx.bodies.subscribe_pet_clicks(_click_listener(clicked, personas))
    try:
        await ctx.bodies.show_persona_picker(persona_options(personas))
        timer = ctx.countdown("persona_pick", ctx.session.persona_pick_s)
        chosen = await ctx.until(timer, lambda: _ask(ctx, personas, clicked))
    finally:
        unsubscribe()
        with contextlib.suppress(Exception):  # hide the cards, also on a WoZ jump / stop
            await asyncio.shield(ctx.bodies.show_persona_picker([]))
    if chosen is None:
        _choose(ctx, default, "timeout")
        await ctx.say_line("persona_default", expression="happy")
        return Next("GREETING", "timer")
    persona_id, method = chosen
    _choose(ctx, persona_id, method)
    await ctx.say_line("persona_chosen", expression="happy", gesture="nod")
    return Next("GREETING")


def _click_listener(
    clicked: asyncio.Future[str], personas: dict[str, Persona]
) -> Callable[[str], None]:
    """Resolve ``clicked`` with the first click on a known persona card ("persona:<id>")."""

    def on_click(target: str) -> None:
        persona_id = target.removeprefix(PERSONA_CLICK_PREFIX)
        known = target.startswith(PERSONA_CLICK_PREFIX) and persona_id in personas
        if known and not clicked.done():
            clicked.set_result(persona_id)

    return on_click


async def _ask(
    ctx: PhaseContext, personas: dict[str, Persona], clicked: asyncio.Future[str]
) -> tuple[str, str]:
    """A click on a card or a recognised spoken choice, whichever comes first."""
    if clicked.done():
        return clicked.result(), "click"
    voice = asyncio.ensure_future(_ask_by_voice(ctx, personas))
    winner = await first_of(clicked, voice)
    return (clicked.result(), "click") if winner == 0 else (voice.result(), "voice")


async def _ask_by_voice(ctx: PhaseContext, personas: dict[str, Persona]) -> str:
    """Listen until a persona is recognised (the countdown above ends it otherwise)."""
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
