"""WebSocket message protocol between the brain and the bodies (desktop pet, fake robot).

This file is mirrored EXACTLY by ``shared/protocol.ts``. Change both in the same step.
``shared/fixtures/protocol_examples.json`` is validated by the tests on both sides, so a
change made on only one side fails a test.

Every message is JSON: ``{"type": "...", "id": "<uuid>", "ts": <epoch_ms>, ...payload}``.
Unknown fields are rejected so mismatches show up immediately instead of being ignored.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

EyeState = Literal[
    "idle",
    "blink",
    "listening",
    "thinking",
    "happy",
    "sad",
    "surprised",
    "determined",
    "sleepy",
    "off",
    "countdown",
    "signal_go",
]

Expression = Literal["idle", "happy", "surprised", "thinking", "sad", "sleepy", "determined"]

BodyName = Literal["desktop_pet", "fake_robot"]


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_ms() -> int:
    return int(time.time() * 1000)


class Envelope(BaseModel):
    """Fields every message has."""

    # strict: no type coercion ("100" is not an int), same as the zod schemas in protocol.ts
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(default_factory=_new_id, min_length=1)
    ts: int = Field(default_factory=_now_ms, ge=0)


# --- Brain -> body ---------------------------------------------------------------------------


class Activate(Envelope):
    type: Literal["activate"] = "activate"
    entrance: Literal["jump_in", "wake_up", "fade_in"]


class Deactivate(Envelope):
    type: Literal["deactivate"] = "deactivate"
    exit: Literal["jump_out", "sleep", "fade_out"]


class Speak(Envelope):
    type: Literal["speak"] = "speak"
    text: str
    audio_b64: str | None = None  # tts-1 audio; absent = captions only
    expression: Expression = "idle"


class Eyes(Envelope):
    type: Literal["eyes"] = "eyes"
    state: EyeState


class Motion(Envelope):
    type: Literal["motion"] = "motion"
    name: str = Field(min_length=1)  # a named motion from config/motions.yaml


class Caption(Envelope):
    type: Literal["caption"] = "caption"
    text: str | None  # None hides the caption


BrainToBody = Annotated[
    Activate | Deactivate | Speak | Eyes | Motion | Caption,
    Field(discriminator="type"),
]


# --- Body -> brain ---------------------------------------------------------------------------


class Hello(Envelope):
    type: Literal["hello"] = "hello"
    body: BodyName
    version: str = Field(min_length=1)


class Ack(Envelope):
    type: Literal["ack"] = "ack"
    ref_id: str = Field(min_length=1)
    ok: bool
    error: str | None = None


class SpeechDone(Envelope):
    type: Literal["speech_done"] = "speech_done"
    ref_id: str = Field(min_length=1)
    duration_ms: int = Field(ge=0)


class UserClick(Envelope):
    type: Literal["user_click"] = "user_click"
    target: str = Field(min_length=1)


BodyToBrain = Annotated[
    Hello | Ack | SpeechDone | UserClick,
    Field(discriminator="type"),
]


BRAIN_TO_BODY: TypeAdapter[BrainToBody] = TypeAdapter(BrainToBody)
BODY_TO_BRAIN: TypeAdapter[BodyToBrain] = TypeAdapter(BodyToBrain)


def parse_body_message(raw: str | bytes) -> BodyToBrain:
    """Parse and validate a JSON message sent by a body. Raises pydantic.ValidationError."""
    return BODY_TO_BRAIN.validate_json(raw)


def encode(message: BrainToBody | BodyToBrain) -> str:
    """Serialise a message to JSON for sending over the WebSocket."""
    return message.model_dump_json()
