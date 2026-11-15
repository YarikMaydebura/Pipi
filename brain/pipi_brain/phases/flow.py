"""The phase order of docs/INTERACTION_FLOW.md §1 and which body side each phase uses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from pipi_brain.protocol import Phase

Side = Literal["pet", "robot"]
Trigger = Literal["auto", "timer", "woz", "user", "error"]
# goto: to ``target``; next: the successor; restart: the current phase again (after an
# emergency stop); halt: emergency stop; break_over: break_max_s; end_game: end the game.
DirectiveKind = Literal["goto", "next", "restart", "halt", "break_over", "end_game"]

PHASES: tuple[Phase, ...] = get_args(Phase)

# The natural successor of every phase (GAME_CHOSEN depends on the game loop setting).
SUCCESSOR: dict[Phase, Phase] = {
    "SETUP": "PERSONA_PICK",
    "PERSONA_PICK": "GREETING",
    "GREETING": "FOCUS",
    "FOCUS": "MIGRATE_OUT",
    "MIGRATE_OUT": "ROBOT_WAKE",
    "ROBOT_WAKE": "CHAT",
    "CHAT": "GAME_CROCODILE",
    "GAME_CROCODILE": "GAME_MENU",
    "GAME_MENU": "GAME_CHOSEN",
    "GAME_CHOSEN": "ROBOT_GOODBYE",
    "ROBOT_GOODBYE": "MIGRATE_IN",
    "MIGRATE_IN": "RETURN",
    "RETURN": "END",
}

PET_PHASES: frozenset[Phase] = frozenset({"PERSONA_PICK", "GREETING", "FOCUS", "RETURN"})
# The break: everything that happens on the robot side (break_max_s applies here).
BREAK_PHASES: frozenset[Phase] = frozenset(
    {"ROBOT_WAKE", "CHAT", "GAME_CROCODILE", "GAME_MENU", "GAME_CHOSEN", "ROBOT_GOODBYE"}
)
GAME_PHASES: frozenset[Phase] = frozenset({"GAME_CROCODILE", "GAME_CHOSEN"})


def side_of(phase: Phase) -> Side | None:
    """Which body a phase runs on (None: SETUP, END and the migrations themselves)."""
    if phase in PET_PHASES:
        return "pet"
    if phase in BREAK_PHASES:
        return "robot"
    return None


def successor(phase: Phase, *, game_loop: bool) -> Phase | None:
    """Next phase in the normal flow; None after END."""
    if phase == "GAME_CHOSEN" and game_loop:
        return "GAME_MENU"
    return SUCCESSOR.get(phase)


def is_phase(value: str) -> bool:
    return value in PHASES


@dataclass(frozen=True)
class Directive:
    """A request to change the flow (from the WoZ or a session timer), applied by the
    controller at the next safe point."""

    kind: DirectiveKind
    target: Phase | None = None
    trigger: Trigger = "woz"
    command: str | None = None
    reason: str | None = None
