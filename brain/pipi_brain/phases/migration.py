"""MIGRATE_OUT and MIGRATE_IN: the core moment, identical for every participant.

The choreography itself lives in ``BodyManager`` (bodies/manager.py); these handlers add the
speech, the break timer and the fallback when the robot is not there:

OUT: whole migration is one safe point (WoZ waits until Pipi has landed).
     pet: signature line + signature wave -> jump_out -> flight -> robot wake_up -> ROBOT_WAKE.
     Robot missing / does not wake: Pipi stays on the screen, says so, the break runs on the
     pet (CHAT next), the WoZ gets an alert.
IN : robot sleep -> flight -> pet jump_in -> RETURN. If the break ran on the pet: nothing to do.
"""

from __future__ import annotations

import contextlib

from pipi_brain.bodies.base import Body
from pipi_brain.phases.context import MissingLineValue, Next, PhaseContext


def wake_line(ctx: PhaseContext) -> tuple[str, dict[str, str]]:
    """The ROBOT_WAKE greeting (also prefetched during the jump)."""
    cues = ctx.app.cues
    base = "robot_wake" if cues.signature_phrase else "robot_wake_plain"
    name = ctx.state.memory.name
    if name and cues.memory_references:
        return base, {"name": name}
    return f"{base}_noname", {}


async def run_out(ctx: PhaseContext) -> Next:
    after = ctx.state.after_migration
    ctx.state.after_migration = None
    if ctx.bodies.active_side == "robot":
        ctx.log("migration", {"direction": "out", "stage": "skipped", "reason": "already on robot"})
        return Next(after or "ROBOT_WAKE")
    ctx.state.break_on_pet = False
    _start_break_timer(ctx)
    gesture = "signature_wave" if ctx.app.cues.signature_gesture else "wave"

    async def announce(pet: Body) -> None:
        await ctx.say_line("migration_announce", body=pet, gesture=gesture, expression="happy")

    async with ctx.safe.critical():
        line_id, values = wake_line(ctx)
        with contextlib.suppress(MissingLineValue):
            ctx.voice.prefetch(ctx.line(line_id, **values))  # ready when the robot wakes
        result = await ctx.bodies.migrate_out(announce)
        if not result.success:
            ctx.state.break_on_pet = True
            await ctx.say_line("migration_unavailable", expression="sad")
    if ctx.state.break_on_pet:
        return Next(after if after and after != "ROBOT_WAKE" else "CHAT")
    return Next(after or "ROBOT_WAKE")


async def run_in(ctx: PhaseContext) -> Next:
    after = ctx.state.after_migration
    ctx.state.after_migration = None
    _stop_break_timer(ctx)
    if ctx.bodies.active_side == "pet" or ctx.bodies.active_side is None:
        reason = "break ran on the pet" if ctx.state.break_on_pet else "already on the pet"
        ctx.log("migration", {"direction": "in", "stage": "skipped", "reason": reason})
        ctx.state.break_on_pet = False
        if ctx.bodies.active_side is None:
            await ctx.bodies.appear_on_pet()
        return Next(after or "RETURN")
    async with ctx.safe.critical():
        await ctx.bodies.migrate_in()
    ctx.state.break_on_pet = False
    return Next(after or "RETURN")


def _start_break_timer(ctx: PhaseContext) -> None:
    limit = ctx.app.timers.break_max_s
    ctx.state.break_timer = ctx.countdown("break", limit, visible=False) if limit else None
    ctx.push_state()


def _stop_break_timer(ctx: PhaseContext) -> None:
    ctx.state.break_timer = None
    ctx.push_state()
