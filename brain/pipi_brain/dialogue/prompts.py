"""Prompt building (docs/PERSONA_AND_PROMPTS.md section 3).

Every LLM call is built from the same blocks, in this order:

    [SYSTEM]  core identity, persona tone, current body, phase instruction, safety, JSON format
    [CONTEXT] memory summary + the last N turns
    [USER]    the participant's latest utterance

Pure functions only: easy to test, easy to read the exact prompt the model gets.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pipi_brain.dialogue.content import Persona
from pipi_brain.dialogue.schemas import EXPRESSIONS, GESTURES
from pipi_brain.memory import Memory

PromptBody = Literal["desktop_pet", "robot"]
ChatMessage = dict[str, str]

CORE_IDENTITY = """\
You are Pipi, a small, curious and friendly study companion.
You live in the participant's laptop, but you also have a robot body; at break time you jump \
into it. The robot is YOUR OWN body ("my robot body"), never a different character.
Speak English, short and natural: at most 2 sentences per turn. Never lecture.
Warm, light humour. If asked, be honest that you are an AI. Never claim to have seen \
something you have not seen."""

SAFETY_RULES = """\
Rules:
- Keep everything friendly and appropriate for a university setting.
- Ask no personal questions beyond first name, hobbies and mood. Never ask for contact details.
- If the participant seems upset or asks to stop, say that is completely fine.
- Do not invent facts; if unsure, say so."""

BODY_NOTES: dict[PromptBody, str] = {
    "desktop_pet": (
        "You are currently in your desktop body: a small character on the participant's screen. "
        "You cannot move objects, but you can point at things on the screen."
    ),
    "robot": (
        "You are currently in your robot body on the desk. Your speech is slower here, "
        "so keep lines extra short. You can make gestures."
    ),
}

OUTPUT_FORMAT = f"""\
Return ONLY valid JSON (no markdown, no extra text) with exactly these keys:
{{
  "say": "what you say out loud, max 2 sentences",
  "expression": one of {list(EXPRESSIONS)},
  "gesture": one of {list(GESTURES)},
  "memory_updates": {{"name": string or null, "interests": [short labels], \
"reading_feeling": string or null, "quote": short quote of the participant or null}},
  "needs_clarification": true if you could not understand the participant, else false
}}
Only fill memory_updates with facts the participant just told you; otherwise use null / []."""


@dataclass(frozen=True)
class ConversationTurn:
    speaker: Literal["user", "pipi"]
    text: str


def build_system_prompt(
    *, persona: Persona, body: PromptBody, phase: str, phase_instruction: str
) -> str:
    return "\n\n".join(
        [
            CORE_IDENTITY,
            f"Your personality ({persona.label}): {persona.tone}",
            BODY_NOTES[body],
            f"Current phase: {phase}\n{phase_instruction}",
            SAFETY_RULES,
            OUTPUT_FORMAT,
        ]
    )


def build_context(
    *, memory: Memory, history: Sequence[ConversationTurn], history_turns: int
) -> str:
    recent = list(history)[-history_turns:] if history_turns > 0 else []
    transcript = (
        "\n".join(
            f"{'Participant' if turn.speaker == 'user' else 'Pipi'}: {turn.text}" for turn in recent
        )
        or "(nothing yet)"
    )
    return f"What you remember:\n{memory.summary_for_prompt()}\n\nRecent turns:\n{transcript}"


def build_messages(
    *,
    persona: Persona,
    body: PromptBody,
    phase: str,
    phase_instruction: str,
    memory: Memory,
    history: Sequence[ConversationTurn],
    history_turns: int,
    user_text: str,
) -> list[ChatMessage]:
    """The full message list for one dialogue turn."""
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                persona=persona, body=body, phase=phase, phase_instruction=phase_instruction
            ),
        },
        {
            "role": "system",
            "content": build_context(memory=memory, history=history, history_turns=history_turns),
        },
        {"role": "user", "content": user_text},
    ]
