"""JSON output schemas of the LLM (docs/PERSONA_AND_PROMPTS.md section 5).

Validation is strict where it matters (``say`` must exist and be short enough to speak) and
lenient where a small mistake is harmless (an unknown expression becomes ``idle``, an unknown
gesture becomes ``none``, extra keys are ignored). Anything that fails raises
:class:`InvalidModelOutput`, which triggers one retry and then the scripted fallback line.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from pipi_brain.memory import MemoryUpdates
from pipi_brain.protocol import Expression

Gesture = Literal[
    "none", "nod", "shake_head", "think", "excited", "celebrate", "shrug", "wave", "signature_wave"
]

EXPRESSIONS: tuple[str, ...] = get_args(Expression)
GESTURES: tuple[str, ...] = get_args(Gesture)
MAX_SAY_CHARS = 400  # ~2-3 spoken sentences; longer means the model ignored the rules

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class InvalidModelOutput(Exception):
    """The LLM answered, but not with valid JSON matching the schema."""


class DialogueTurn(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    say: str = Field(min_length=1, max_length=MAX_SAY_CHARS)
    expression: Expression = "idle"
    gesture: Gesture = "none"
    memory_updates: MemoryUpdates = MemoryUpdates()
    needs_clarification: bool = False

    @field_validator("say", mode="before")
    @classmethod
    def _strip_say(cls, value: Any) -> Any:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("expression", mode="before")
    @classmethod
    def _known_expression(cls, value: Any) -> Any:
        return value if value in EXPRESSIONS else "idle"

    @field_validator("gesture", mode="before")
    @classmethod
    def _known_gesture(cls, value: Any) -> Any:
        return value if value in GESTURES else "none"

    @field_validator("memory_updates", mode="before")
    @classmethod
    def _null_updates(cls, value: Any) -> Any:
        return {} if value is None else value


def parse_dialogue_turn(raw: str) -> DialogueTurn:
    """Parse the model's text into a DialogueTurn or raise InvalidModelOutput."""
    text = _CODE_FENCE.sub("", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidModelOutput(f"not valid JSON ({exc.msg} at char {exc.pos})") from exc
    if not isinstance(data, dict):
        raise InvalidModelOutput(f"expected a JSON object, got {type(data).__name__}")
    try:
        return DialogueTurn.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'root'}: {err['msg']}"
            for err in exc.errors()
        )
        raise InvalidModelOutput(f"schema mismatch: {problems}") from exc
