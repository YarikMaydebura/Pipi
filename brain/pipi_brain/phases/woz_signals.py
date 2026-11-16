"""Hand signals from the experimenter to a running game.

When the WoZ plays a motion by hand (``play_motion``), the controller publishes its name
here. A game may be waiting for exactly that: in the quick-draw duel ``duel_hit`` means "the
robot is hit, the participant wins this round" and ``duel_win`` means "the robot wins". That
way the experimenter can score a round with the existing command set (no protocol change).
Nobody waiting = nothing happens (the motion is simply played).
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection


class WozSignals:
    """Motions the experimenter played by hand; a running game may be waiting for one."""

    def __init__(self) -> None:
        self._waiters: list[tuple[frozenset[str], asyncio.Future[str]]] = []

    def publish(self, motion: str) -> bool:
        """Tell waiting games; True if one of them was waiting for this motion."""
        delivered = False
        for names, future in list(self._waiters):
            if motion in names and not future.done():
                future.set_result(motion)
                delivered = True
        return delivered

    async def wait(self, names: Collection[str]) -> str:
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        entry = (frozenset(names), future)
        self._waiters.append(entry)
        try:
            return await future
        finally:
            self._waiters.remove(entry)
