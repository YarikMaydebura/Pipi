"""Argument rules for every WoZ command (docs/INTERACTION_FLOW.md §4). Pure, never raises.

Argument names (the WoZ panel sends exactly these):

| command | args |
|---|---|
| start_session | participant_id? (must match the brain's), override? (bool; study mode:  |
|   | start although pet/robot are not connected) |
| goto_phase | phase (SETUP ... END) |
| extend_focus | seconds (number, 1..600) |
| say | line_id (id from lines.yaml) |
| say_text | text (1..300 characters) |
| start_game | game (game id, e.g. quick_draw) |
| switch_robot_body | body ("fake" or "real") |
| set_eyes | state (EyeState), body? (body name) |
| play_motion | name (motion name), body? (body name) |
| everything else | none |

Whether a command makes sense *right now* (e.g. extend_focus outside FOCUS) is checked by
the session controller; this module only checks the shape of the arguments.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import get_args

from pipi_brain.protocol import EyeState, Phase, WozCommand, WozCommandName

MAX_SAY_TEXT = 300
MAX_EXTEND_S = 600
NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
ArgValue = str | int | float | bool


@dataclass(frozen=True)
class Arg:
    name: str
    kind: str  # "text" | "number" | "bool" | "name" (a-z0-9_) | "choice"
    required: bool = True
    choices: frozenset[str] = frozenset()
    min_value: float | None = None
    max_value: float | None = None
    max_len: int = 64


PHASES = frozenset(get_args(Phase))
EYE_STATES = frozenset(get_args(EyeState))

COMMAND_ARGS: Mapping[WozCommandName, tuple[Arg, ...]] = {
    "start_session": (
        Arg("participant_id", "text", required=False, max_len=32),
        Arg("override", "bool", required=False),
    ),
    "next_phase": (),
    "goto_phase": (Arg("phase", "choice", choices=PHASES),),
    "extend_focus": (Arg("seconds", "number", min_value=1, max_value=MAX_EXTEND_S),),
    "trigger_migration_out": (),
    "trigger_migration_in": (),
    "say": (Arg("line_id", "name"),),
    "say_text": (Arg("text", "text", max_len=MAX_SAY_TEXT),),
    "start_game": (Arg("game", "name"),),
    "end_game": (),
    "switch_robot_body": (Arg("body", "choice", choices=frozenset({"fake", "real"})),),
    "set_eyes": (Arg("state", "choice", choices=EYE_STATES), Arg("body", "name", required=False)),
    "play_motion": (Arg("name", "name"), Arg("body", "name", required=False)),
    "pause": (),
    "resume": (),
    "emergency_stop": (),
    "end_session": (),
}


def validate_command(command: WozCommand) -> str | None:
    """None if the command is well-formed, else a short error for the panel."""
    if command.reason == "other" and not (command.note and command.note.strip()):
        return "reason 'other' needs a note (free text)"
    specs = COMMAND_ARGS.get(command.command)
    if specs is None:
        return f"unknown command {command.command}"
    known = {spec.name for spec in specs}
    unknown = sorted(set(command.args) - known)
    if unknown:
        allowed = ", ".join(sorted(known)) or "none"
        return f"{command.command}: unknown argument(s) {', '.join(unknown)} (allowed: {allowed})"
    for spec in specs:
        error = _check(spec, command.args.get(spec.name))
        if error:
            return f"{command.command}: {error}"
    return None


def _check(spec: Arg, value: ArgValue | None) -> str | None:
    if value is None:
        return f"'{spec.name}' is required" if spec.required else None
    if spec.kind == "bool":
        return None if isinstance(value, bool) else f"'{spec.name}' must be true or false"
    if spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"'{spec.name}' must be a number"
        low, high = spec.min_value, spec.max_value
        if (low is not None and value < low) or (high is not None and value > high):
            return f"'{spec.name}' must be between {low:g} and {high:g}"
        return None
    if not isinstance(value, str):
        return f"'{spec.name}' must be text"
    if spec.kind == "choice":
        if value not in spec.choices:
            return f"'{spec.name}' must be one of: {', '.join(sorted(spec.choices))}"
        return None
    if spec.kind == "name" and not NAME_PATTERN.fullmatch(value):
        return f"'{spec.name}' must be a short lowercase name (a-z, 0-9, _)"
    if not value.strip():
        return f"'{spec.name}' must not be empty"
    if len(value) > spec.max_len:
        return f"'{spec.name}' is too long (max {spec.max_len} characters)"
    return None
