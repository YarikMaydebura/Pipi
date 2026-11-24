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

RobotSide = Literal["left", "right"]


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
    # base64 of a complete WAV file (16-bit PCM mono, 24 kHz from the TTS model);
    # absent = captions only
    audio_b64: str | None = None
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


class BodyConfig(Envelope):
    """Sent once right after ``hello``: settings the body needs (e.g. where the robot stands)."""

    type: Literal["body_config"] = "body_config"
    robot_side: RobotSide  # screen edge facing the robot: Pipi jumps off / lands on this side


class Calm(Envelope):
    """Calm mode on/off: during FOCUS the pet stays quiet (no fidgets, tiny reactions only)."""

    type: Literal["calm"] = "calm"
    on: bool


class PersonaOption(BaseModel):
    """One persona card on the pet (from config/personas.yaml)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")  # sent back as user_click "persona:<id>"
    label: str = Field(min_length=1, max_length=40)
    description: str = Field(max_length=120)


PERSONA_CLICK_PREFIX = "persona:"  # user_click target of a persona card: "persona:<id>"


class PersonaPicker(Envelope):
    """Show the persona cards next to Pipi (pet only); an empty list hides them.

    A click on a card comes back as ``user_click`` with target ``"persona:<id>"``.
    """

    type: Literal["persona_picker"] = "persona_picker"
    options: list[PersonaOption] = Field(max_length=6)


class Stop(Envelope):
    """Emergency stop: end speech audio and motion at once, hide the caption, idle eyes.

    The body stays active (awake / on screen); it acks as soon as everything has stopped and
    sends no ``speech_done`` for the interrupted speech.
    """

    type: Literal["stop"] = "stop"


BrainToBody = Annotated[
    Activate
    | Deactivate
    | Speak
    | Eyes
    | Motion
    | Caption
    | BodyConfig
    | Calm
    | PersonaPicker
    | Stop,
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


# --- WoZ <-> brain (experimenter panel, docs/INTERACTION_FLOW.md §4) ------------------------

Phase = Literal[
    "SETUP",
    "PERSONA_PICK",
    "GREETING",
    "FOCUS",
    "MIGRATE_OUT",
    "ROBOT_WAKE",
    "CHAT",
    "GAME_CROCODILE",
    "GAME_MENU",
    "GAME_CHOSEN",
    "ROBOT_GOODBYE",
    "MIGRATE_IN",
    "RETURN",
    "END",
]

WozCommandName = Literal[
    "start_session",
    "next_phase",
    "goto_phase",
    "extend_focus",
    "trigger_migration_out",
    "trigger_migration_in",
    "say",
    "say_text",
    "start_game",
    "end_game",
    "switch_robot_body",
    "set_eyes",
    "play_motion",
    "pause",
    "resume",
    "emergency_stop",
    "end_session",
]

WozReason = Literal[
    "technical_failure",
    "participant_confused",
    "timing",
    "participant_request",
    "demo",
    "other",
]

ActiveBody = Literal["desktop_pet", "fake_robot", "alpha_mini"]


class WozCommand(Envelope):
    """Every experimenter action, always with a reason (logged for the study)."""

    type: Literal["woz_command"] = "woz_command"
    command: WozCommandName
    # command arguments, e.g. {"phase": "CHAT"}, {"seconds": 60}; validated per command by the brain
    args: dict[str, str | int | float | bool] = Field(default_factory=dict)
    reason: WozReason
    note: str | None = None  # free text, required by the panel when reason == "other"


class Strict(BaseModel):
    """Nested payload objects: same strictness as the messages."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TimerInfo(Strict):
    name: str = Field(min_length=1)  # e.g. "focus", "break"
    remaining_s: float = Field(ge=0)
    total_s: float = Field(ge=0)


class BodyHealth(Strict):
    connected: bool
    last_error: str | None = None


class TurnLatencies(Strict):
    stt_ms: int | None = Field(default=None, ge=0)
    llm_ms: int | None = Field(default=None, ge=0)
    tts_ms: int | None = Field(default=None, ge=0)
    total_ms: int | None = Field(default=None, ge=0)


class StateUpdate(Envelope):
    """Sent to the WoZ panel on every change (and as the first message after it connects)."""

    type: Literal["state_update"] = "state_update"
    phase: Phase
    mode: Literal["dev", "study", "demo"]
    participant_id: str | None = None
    active_body: ActiveBody | None = None
    timer: TimerInfo | None = None
    paused: bool = False
    memory_summary: dict[str, str] = Field(default_factory=dict)
    health: dict[str, BodyHealth] = Field(default_factory=dict)  # body name -> health


class Turn(Envelope):
    type: Literal["turn"] = "turn"
    speaker: Literal["user", "pipi"]
    text: str
    latencies: TurnLatencies | None = None


class Alert(Envelope):
    type: Literal["alert"] = "alert"
    level: Literal["info", "warning", "error"]
    message: str = Field(min_length=1)


BrainToWoz = Annotated[StateUpdate | Turn | Alert | Ack, Field(discriminator="type")]
WozToBrain = WozCommand


BRAIN_TO_BODY: TypeAdapter[BrainToBody] = TypeAdapter(BrainToBody)
BODY_TO_BRAIN: TypeAdapter[BodyToBrain] = TypeAdapter(BodyToBrain)
BRAIN_TO_WOZ: TypeAdapter[BrainToWoz] = TypeAdapter(BrainToWoz)


def parse_body_message(raw: str | bytes) -> BodyToBrain:
    """Parse and validate a JSON message sent by a body. Raises pydantic.ValidationError."""
    return BODY_TO_BRAIN.validate_json(raw)


def parse_woz_message(raw: str | bytes) -> WozToBrain:
    """Parse and validate a JSON message sent by the WoZ panel. Raises pydantic.ValidationError."""
    return WozCommand.model_validate_json(raw)


def encode(message: BrainToBody | BodyToBrain | BrainToWoz | WozToBrain) -> str:
    """Serialise a message to JSON for sending over the WebSocket."""
    return message.model_dump_json()
