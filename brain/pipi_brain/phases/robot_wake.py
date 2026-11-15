"""ROBOT_WAKE: the robot greets the participant by name with the signature phrase + gesture.

"Ta-da! Hi again, {name}!" with ``signature_wave`` (the same wave the pet did before jumping).
The line was prefetched during the migration, so it starts right after the robot wakes up.
Cue flags (config ``cues``) can switch off the phrase, the gesture or the name.
"""

from __future__ import annotations

from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.migration import wake_line


async def run(ctx: PhaseContext) -> Next:
    if ctx.state.break_on_pet:
        return Next("CHAT")  # Pipi never left the screen: no second greeting
    line_id, values = wake_line(ctx)
    gesture = "signature_wave" if ctx.app.cues.signature_gesture else "wave"
    await ctx.say_line(line_id, gesture=gesture, expression="happy", **values)
    if "name" in values:
        ctx.memory_reference(["name"])
    return Next("CHAT")
