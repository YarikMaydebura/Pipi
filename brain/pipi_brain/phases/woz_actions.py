"""What every WoZ command does (docs/INTERACTION_FLOW.md §4). Never raises.

1. ``validate_command``: argument shape (woz_commands.py) and the reason/note rule.
2. Is the command possible *now*? (e.g. ``extend_focus`` only during FOCUS.)
3. Apply: flow commands become directives (applied at the next safe point by the controller);
   body / speech commands act right away; ``emergency_stop`` stops everything immediately.
Every outcome (ok or not) is logged by the controller as ``woz_action``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from pipi_brain.phases.context import MissingLineValue
from pipi_brain.phases.flow import (
    BREAK_PHASES,
    GAME_PHASES,
    PET_PHASES,
    Directive,
    DirectiveKind,
)
from pipi_brain.phases.voice import SayMeta
from pipi_brain.phases.woz_commands import validate_command
from pipi_brain.protocol import EyeState, Phase, WozCommand
from pipi_brain.woz_api import CommandOutcome

if TYPE_CHECKING:
    from pipi_brain.phases.controller import SessionController

OK = CommandOutcome(ok=True)
Action = Callable[["SessionController", WozCommand], Awaitable[CommandOutcome]]


def _fail(error: str) -> CommandOutcome:
    return CommandOutcome(ok=False, error=error)


async def apply_command(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    error = validate_command(command)
    if error is not None:
        return _fail(error)
    return await ACTIONS[command.command](ctl, command)


def _directive(
    ctl: SessionController, kind: DirectiveKind, command: WozCommand, target: Phase | None = None
) -> None:
    ctl.enqueue(
        Directive(
            kind,
            target=target,
            trigger="woz",
            command=command.command,
            reason=command.reason,
        )
    )


def _not_ended(ctl: SessionController) -> CommandOutcome | None:
    return _fail("the session has already ended") if ctl.state.phase == "END" else None


# --- flow --------------------------------------------------------------------------------------


def _start_problem(ctl: SessionController, command: WozCommand) -> str | None:
    if ctl.state.phase != "SETUP":
        return "the session has already started"
    wanted = command.args.get("participant_id")
    if wanted is not None and wanted != ctl.participant_id:
        return (
            f"participant id is {ctl.participant_id} (set when the brain started); "
            "restart the brain with --participant to change it"
        )
    if ctl.app.mode == "study" and command.args.get("override") is not True:
        missing = [
            name
            for name in ("desktop_pet", ctl.bodies.robot_name)
            if (body := ctl.bodies.get(name)) is None or not body.connected
        ]
        if missing:
            return (
                f"not ready: {', '.join(missing)} not connected "
                "(send override=true to start anyway)"
            )
    return None


async def _start_session(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    problem = _start_problem(ctl, command)
    if problem is not None:
        return _fail(problem)
    from pipi_brain.phases.setup import health_report

    ctl.events.log(
        "health_check", {**health_report(ctl.ctx), "override": bool(command.args.get("override"))}
    )
    _directive(ctl, "next", command)
    return OK


async def _next_phase(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    if ctl.state.phase == "SETUP":
        return await _start_session(ctl, command)
    if (ended := _not_ended(ctl)) is not None:
        return ended
    _directive(ctl, "next", command)
    return OK


async def _goto_phase(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    target = cast(Phase, command.args["phase"])
    if (ended := _not_ended(ctl)) is not None:
        return ended
    if target == "SETUP":
        return _fail("cannot go back to SETUP")
    _directive(ctl, "goto", command, target)
    return OK


async def _extend_focus(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    if ctl.state.phase != "FOCUS":
        return _fail("extend_focus only works during FOCUS")
    seconds = float(command.args["seconds"])
    timer = ctl.state.phase_timer
    if timer is not None and timer.name == "focus":
        timer.extend(seconds)
    else:  # FOCUS just started; its handler picks this up when it starts the timer
        ctl.state.focus_extra_s += seconds
    ctl.push_state()
    return OK


async def _migration_out(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    if ctl.state.phase not in PET_PHASES:
        return _fail(f"Pipi is not on the pet in {ctl.state.phase}")
    _directive(ctl, "goto", command, "MIGRATE_OUT")
    return OK


async def _migration_in(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    if ctl.state.phase not in BREAK_PHASES:
        return _fail(f"migration in only works during the break (now {ctl.state.phase})")
    _directive(ctl, "goto", command, "MIGRATE_IN")
    return OK


async def _start_game(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    game = str(command.args["game"])
    if ctl.registry.info(game) is None:
        return _fail(f"unknown game {game}; known: {', '.join(sorted(ctl.registry.known))}")
    if ctl.state.phase not in BREAK_PHASES:
        return _fail("games only during the break (use trigger_migration_out first)")
    ctl.state.chosen_game = game
    _directive(ctl, "goto", command, "GAME_CHOSEN")
    return OK


async def _end_game(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    if ctl.state.phase not in GAME_PHASES:
        return _fail("no game is running")
    _directive(ctl, "end_game", command)
    return OK


async def _end_session(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    if (ended := _not_ended(ctl)) is not None:
        return ended
    _directive(ctl, "goto", command, "END")
    return OK


# --- speech ------------------------------------------------------------------------------------


async def _say(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    line_id = str(command.args["line_id"])
    if line_id not in ctl.content.lines:
        return _fail(f"no line {line_id!r} in lines.yaml")
    values: dict[str, str] = {}
    if ctl.state.memory.name:
        values["name"] = ctl.state.memory.name
    try:
        ctl.ctx.line(line_id, **values)
    except MissingLineValue as exc:
        return _fail(str(exc))
    ctl.spawn(ctl.ctx.say_line(line_id, source="woz", respect_pause=False, **values))
    return OK


async def _say_text(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    text = " ".join(str(command.args["text"]).split())
    meta = SayMeta(source="woz", fallback="woz_text")
    ctl.spawn(ctl.voice.say(text, meta, respect_pause=False))
    return OK


# --- bodies ------------------------------------------------------------------------------------


def _body_arg(ctl: SessionController, command: WozCommand) -> tuple[str | None, str | None]:
    """(body name or None for the active body, error)."""
    body = command.args.get("body")
    if body is None:
        if ctl.bodies.active_name is None:
            return None, "no active body yet (pass body=...)"
        return None, None
    if str(body) not in ctl.bodies.names:
        return None, f"unknown body {body}; bodies: {', '.join(ctl.bodies.names)}"
    return str(body), None


async def _set_eyes(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    body, error = _body_arg(ctl, command)
    if error is not None:
        return _fail(error)
    result = await ctl.bodies.set_eyes(cast(EyeState, command.args["state"]), body)
    return OK if result.ok else _fail(result.error or "body error")


async def _play_motion(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    body, error = _body_arg(ctl, command)
    if error is not None:
        return _fail(error)
    result = await ctl.bodies.play_motion(str(command.args["name"]), body)
    return OK if result.ok else _fail(result.error or "body error")


async def _switch_robot_body(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    target: Any = command.args["body"]
    async with ctl.safe.critical():
        error = await ctl.bodies.switch_robot_body(target)
    ctl.push_state()
    return OK if error is None else _fail(error)


# --- pause / stop ------------------------------------------------------------------------------


async def _pause(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    if not ctl.pause.pause():
        return _fail("already paused")
    ctl.events.alert("info", "Paused: timers and listening are frozen.")
    ctl.push_state()
    return OK


async def _resume(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    resumed = ctl.pause.resume()
    if ctl.state.halted:
        _directive(ctl, "restart", command)  # restart the stopped phase from its beginning
    elif not resumed:
        return _fail("not paused")
    ctl.push_state()
    return OK


async def _emergency_stop(ctl: SessionController, command: WozCommand) -> CommandOutcome:
    ctl.emergency_stop()
    return OK


ACTIONS: dict[str, Action] = {
    "start_session": _start_session,
    "next_phase": _next_phase,
    "goto_phase": _goto_phase,
    "extend_focus": _extend_focus,
    "trigger_migration_out": _migration_out,
    "trigger_migration_in": _migration_in,
    "say": _say,
    "say_text": _say_text,
    "start_game": _start_game,
    "end_game": _end_game,
    "switch_robot_body": _switch_robot_body,
    "set_eyes": _set_eyes,
    "play_motion": _play_motion,
    "pause": _pause,
    "resume": _resume,
    "emergency_stop": _emergency_stop,
    "end_session": _end_session,
}
