"""Listening and answering, shared by every phase that talks with the participant.

``listen`` waits for the participant (listening eyes), with the "no dead air" rule: after
``timers.silence_reprompt_s`` one gentle re-prompt, after another one it gives up and the
phase continues with its default. Empty or failed transcripts get ONE clarification
("Sorry, could you say that again?"), then the phase default. WoZ pause freezes listening.

``reply`` asks the LLM for a JSON turn (persona, body, phase, memory, recent turns), applies
memory updates and speaks the answer. Reuses the M1 pieces: ``build_messages``,
``DialogueEngine`` (retry + fallback line), ``Memory``, STT with ``timed_call``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

from pipi_brain.dialogue.prompts import build_messages
from pipi_brain.dialogue.schemas import DialogueTurn
from pipi_brain.phases.clock import cancel_and_wait
from pipi_brain.phases.context import PhaseContext
from pipi_brain.phases.inputs import TypedLine, UserInput
from pipi_brain.phases.timers import Countdown
from pipi_brain.phases.voice import SayMeta
from pipi_brain.protocol import Turn
from pipi_brain.resilience import timed_call
from pipi_brain.speech.audio_utils import samples_to_wav
from pipi_brain.speech.base import Utterance


@dataclass(frozen=True)
class Heard:
    text: str
    start: float  # perf_counter when the input arrived (end of speech / typed line)
    stt_ms: int | None


@dataclass(frozen=True)
class NoAnswer:
    reason: Literal["silence", "unclear"]


async def listen(ctx: PhaseContext, *, silence_s: float | None, reprompt: bool) -> Heard | NoAnswer:
    """Wait for the participant. ``silence_s`` None = wait as long as the phase lasts."""
    reprompted = False
    clarified = False
    while True:
        await ctx.bodies.set_eyes("listening")
        got = await _wait_for_input(ctx, silence_s)
        if got is None:
            waited = silence_s or 0.0
            if reprompt and not reprompted:
                ctx.log("silence_reprompt", {"waited_s": waited, "action": "reprompt"})
                await ctx.say_line("silence_reprompt")
                reprompted = True
                continue
            ctx.log("silence_reprompt", {"waited_s": waited, "action": "default"})
            return NoAnswer("silence")
        start = time.perf_counter()
        ctx.voice.thinking_soon()
        if isinstance(got, TypedLine):
            _user_turn(ctx, got.text, input_mode="typed")
            return Heard(got.text, start, None)
        text, stt_ms, problem = await _transcribe(ctx, got)
        if text is not None:
            _user_turn(
                ctx,
                text,
                input_mode="voice",
                stt_ms=stt_ms,
                audio_ms=got.duration_ms,
                truncated=got.truncated,
            )
            return Heard(text, start, stt_ms)
        if clarified:
            return NoAnswer("unclear")
        clarified = True
        await ctx.say_line("stt_retry", start=start, stt_ms=stt_ms, fallback=problem)


async def reply(
    ctx: PhaseContext,
    user_text: str,
    *,
    heard: Heard | None = None,
    fallback_line: str = "llm_fallback",
    extra_instruction: str | None = None,
    gesture: str | None = None,
) -> DialogueTurn:
    """One LLM turn, spoken on the active body. ``user_text`` may also be an ``<event>``."""
    if heard is None:
        ctx.voice.thinking_soon()
    state = ctx.state
    instruction = ctx.content.phase_instruction(state.phase)
    if extra_instruction:
        instruction = f"{instruction}\n\n{extra_instruction}"
    messages = build_messages(
        persona=ctx.content.persona(state.persona),
        body=ctx.prompt_body(),
        phase=state.phase,
        phase_instruction=instruction,
        memory=state.memory,
        history=state.history[:-1] if heard is not None else state.history,
        history_turns=ctx.app.dialogue.history_turns,
        user_text=user_text,
    )
    result = await ctx.dialogue.respond(messages, ctx.line(fallback_line))
    for attempt, error in enumerate(result.errors, start=1):
        ctx.log(
            "llm_error",
            {
                "error": error,
                "attempt": attempt,
                "retry": attempt < result.attempts,
                "fallback": result.fallback_used and attempt == len(result.errors),
            },
        )
    turn = result.turn
    ctx.remember(turn.memory_updates)
    if turn.needs_clarification:
        ctx.log("clarification", {"reason": "unclear"})
    meta = SayMeta(
        line_id=fallback_line if result.fallback_used else None,
        expression=turn.expression,
        gesture=gesture or turn.gesture,
        fallback="llm_fallback" if result.fallback_used else None,
        start=heard.start if heard is not None else None,
        stt_ms=heard.stt_ms if heard is not None else None,
        llm_ms=result.llm_ms,
        llm_attempts=result.attempts,
    )
    await ctx.voice.say(turn.say, meta, cacheable=result.fallback_used)
    return turn


# --- helpers -------------------------------------------------------------------------------


def _user_turn(ctx: PhaseContext, text: str, *, input_mode: str, **extra: object) -> None:
    ctx.state.user_turns += 1
    ctx.state.add_turn("user", text)
    ctx.log("turn", {"speaker": "user", "text": text, "input": input_mode, **extra})
    ctx.events.push(Turn(speaker="user", text=text))
    if input_mode == "voice":
        ctx.emit(f"You: {text}")


async def _transcribe(
    ctx: PhaseContext, utterance: Utterance
) -> tuple[str | None, int | None, str | None]:
    """(text, stt_ms, problem); text None = failed or empty (already logged)."""
    wav = samples_to_wav(utterance.samples, utterance.sample_rate)
    outcome = await timed_call(lambda: ctx.stt.transcribe(wav), ctx.app.timeouts.stt_s)
    if not outcome.ok:
        ctx.log(
            "stt_error",
            {"error": outcome.error, "timed_out": outcome.timed_out, "fallback": "stt_retry"},
        )
        return None, outcome.elapsed_ms, "stt_error"
    text = (outcome.value or "").strip()
    if not text:
        ctx.log("clarification", {"reason": "empty_transcript"})
        return None, outcome.elapsed_ms, "empty"
    return text, outcome.elapsed_ms, None


async def _wait_for_input(ctx: PhaseContext, silence_s: float | None) -> UserInput | None:
    """One input, or None after ``silence_s`` of silence. Paused = not listening."""
    silence = Countdown("silence", silence_s, ctx.pause, ctx.clock) if silence_s else None
    while True:
        await ctx.pause.wait_running()
        input_task = asyncio.ensure_future(ctx.input.next_input())
        paused_task = asyncio.ensure_future(ctx.pause.wait_paused())
        waits: set[asyncio.Future[object]] = {input_task, paused_task}
        silence_task = asyncio.ensure_future(silence.wait_expired()) if silence else None
        if silence_task is not None:
            waits.add(silence_task)
        try:
            done, _ = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            if input_task in done:
                return input_task.result()
            if paused_task in done:
                continue  # listening is frozen; start again after resume
            if ctx.input.hearing:  # silence timer ran out mid-sentence: let them finish
                await cancel_and_wait([paused_task])
                return await input_task
            return None
        finally:
            await cancel_and_wait([task for task in waits if task is not None])
