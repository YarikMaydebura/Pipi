"""Time for the session: an injectable clock and a small "first one wins" helper.

Every phase timer, silence timeout and pause goes through a ``Clock``. The real one uses the
event loop's monotonic time; tests use ``fakes.FakeClock`` (virtual time that jumps ahead
whenever nothing else can run), so a 4-minute focus phase is tested in milliseconds and
always gives the same result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
from typing import Any, Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Monotonic seconds."""
        ...

    async def sleep(self, seconds: float) -> None: ...


class RealClock:
    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


async def cancel_and_wait(tasks: Iterable[asyncio.Future[Any]]) -> None:
    """Cancel tasks and wait until they have really stopped (their errors are ignored).

    If the caller itself is cancelled while waiting, that cancellation is raised as usual
    (it must never be mistaken for one of the tasks stopping).
    """
    pending = [task for task in tasks if not task.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    await asyncio.wait(pending)
    for task in pending:
        if not task.cancelled():
            task.exception()  # looked at, so asyncio does not warn about an unseen error


async def first_of(*awaitables: Awaitable[Any]) -> int:
    """Run the awaitables together; return the index of the first that finished.

    The others are cancelled. An exception in the winner is raised here.
    """
    tasks = [asyncio.ensure_future(aw) for aw in awaitables]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        winner = next(i for i, task in enumerate(tasks) if task in done)
        tasks[winner].result()  # re-raise a failure of the winner
        return winner
    finally:
        await cancel_and_wait(tasks)
