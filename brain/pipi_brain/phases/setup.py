"""SETUP: health check, then wait for the experimenter's ``start_session``.

Without a WoZ panel (``auto_start``) the session starts by itself right after the check.
In study mode ``start_session`` is refused unless the pet and the robot are connected (the
WoZ can override with ``override: true`` + a reason; see the controller).
"""

from __future__ import annotations

import asyncio

from pipi_brain.phases.context import Next, PhaseContext


def health_report(ctx: PhaseContext) -> dict[str, str]:
    report: dict[str, str] = {}
    for name, health in ctx.bodies.health().items():
        status = "connected" if health.connected else "not connected"
        report[name] = (
            f"{status} (last error: {health.last_error})" if health.last_error else status
        )
    report["robot_body"] = ctx.bodies.robot_name
    report["input"] = ctx.input.mode
    return report


async def run(ctx: PhaseContext, *, auto_start: bool) -> Next:
    ctx.log("health_check", health_report(ctx))
    if auto_start:
        return Next("PERSONA_PICK", "auto")
    ctx.emit("Waiting for start_session from the WoZ panel (or type /start) ...")
    await asyncio.Event().wait()  # the WoZ start_session directive ends this phase
    raise AssertionError("unreachable")
