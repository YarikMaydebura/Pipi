"""A stop request must never get lost: timeouts, ``cancel_and_wait`` and the safe-point retry.

Background: on Python 3.11 ``asyncio.wait_for`` throws a cancellation away when the thing it
waits for has just finished. A WoZ command that arrived while Pipi was speaking was then
applied many seconds late (found in a live run on Nov 16).
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from pipi_brain.phases.clock import cancel_and_wait
from pipi_brain.phases.timers import SafePoints
from pipi_brain.resilience import timed_call, with_timeout

REAL_WAIT_S = 1.0
RETRY_S = 0.01


async def _stopped(task: asyncio.Future[object]) -> bool:
    """True if ``task`` ends within a moment (a lost cancellation would leave it running)."""
    done, _ = await asyncio.wait([task], timeout=REAL_WAIT_S)
    if not done:
        task.cancel()
    return bool(done)


async def _instant() -> str:
    return "sent"  # like a local WebSocket send: finishes without waiting


# --- with_timeout ---------------------------------------------------------------------------


async def test_with_timeout_returns_the_value() -> None:
    assert await with_timeout(_instant(), 1) == "sent"


async def test_with_timeout_raises_timeout_error_and_stops_the_work() -> None:
    stopped: list[str] = []

    async def slow() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            stopped.append("stopped")

    with pytest.raises(TimeoutError):
        await with_timeout(slow(), 0.01)

    assert stopped == ["stopped"]


async def test_with_timeout_passes_errors_through() -> None:
    async def broken() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await with_timeout(broken(), 1)


async def test_a_cancel_that_lands_right_after_the_work_finished_is_not_lost() -> None:
    async def phase() -> None:
        await with_timeout(_instant(), 1)
        await asyncio.sleep(10)  # the cancellation has to stop the phase here at the latest

    task = asyncio.ensure_future(phase())
    await asyncio.sleep(0)

    task.cancel()

    assert await _stopped(task) and task.cancelled()


async def test_timed_call_does_not_lose_a_cancellation_either() -> None:
    async def phase() -> None:
        await timed_call(_instant, 1)
        await asyncio.sleep(10)

    task = asyncio.ensure_future(phase())
    await asyncio.sleep(0)

    task.cancel()

    assert await _stopped(task) and task.cancelled()


# --- cancel_and_wait ------------------------------------------------------------------------


async def test_cancel_and_wait_keeps_the_callers_own_cancellation() -> None:
    cleanup_done = asyncio.Event()
    reached: list[str] = []

    async def child() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            await asyncio.shield(cleanup_done.wait())  # a slow clean-up

    async def parent() -> None:
        task = asyncio.ensure_future(child())
        await asyncio.sleep(0)
        await cancel_and_wait([task])
        reached.append("carried on")  # must not happen: the parent itself was cancelled

    task = asyncio.ensure_future(parent())
    for _ in range(3):
        await asyncio.sleep(0)  # the parent now waits for the child's clean-up

    task.cancel()
    cleanup_done.set()

    assert await _stopped(task) and task.cancelled()
    assert reached == []


async def test_cancel_and_wait_ignores_errors_of_the_cancelled_tasks() -> None:
    async def fails_while_stopping() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            raise RuntimeError("clean-up failed")

    task = asyncio.ensure_future(fails_while_stopping())
    await asyncio.sleep(0)

    await cancel_and_wait([task])

    assert task.done() and isinstance(task.exception(), RuntimeError)


# --- SafePoints: the safety net -------------------------------------------------------------


async def test_interrupt_asks_again_when_the_first_cancel_was_swallowed() -> None:
    lost: list[str] = []
    safe = SafePoints(retry_after_s=RETRY_S, on_lost_cancel=lambda: lost.append("lost"))

    async def stubborn() -> None:
        with contextlib.suppress(asyncio.CancelledError):  # some library ate the cancellation
            await asyncio.sleep(10)
        await asyncio.sleep(10)

    task = asyncio.ensure_future(stubborn())
    await asyncio.sleep(0)

    interrupt = asyncio.ensure_future(safe.interrupt(task))

    assert await _stopped(interrupt)
    assert task.cancelled() and lost == ["lost"]


async def test_the_second_cancel_also_waits_for_the_end_of_a_sentence() -> None:
    safe = SafePoints(retry_after_s=RETRY_S)
    order: list[str] = []
    release = asyncio.Event()

    async def stubborn() -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(10)
        async with safe.critical():
            order.append("speaking")
            await release.wait()
            order.append("finished sentence")
        await asyncio.sleep(10)

    task = asyncio.ensure_future(stubborn())
    await asyncio.sleep(0)
    interrupt = asyncio.ensure_future(safe.interrupt(task))
    await asyncio.sleep(RETRY_S * 5)  # several retries could have happened by now

    assert not task.done() and order == ["speaking"]
    release.set()

    assert await _stopped(interrupt)
    assert task.cancelled() and order == ["speaking", "finished sentence"]


async def test_a_normal_interrupt_reports_nothing() -> None:
    lost: list[str] = []
    safe = SafePoints(retry_after_s=RETRY_S, on_lost_cancel=lambda: lost.append("lost"))
    task = asyncio.ensure_future(asyncio.sleep(10))
    await asyncio.sleep(0)

    await safe.interrupt(task)

    assert task.cancelled() and lost == []
