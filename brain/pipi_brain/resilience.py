"""Timeouts for external calls (OpenAI, microphone, speaker) with readable, secret-free errors.

Every network or hardware call goes through :func:`timed_call`. It never raises (except on
cancellation): the caller gets a :class:`CallOutcome` and decides on the fallback and the log
entry. That keeps "timeout + fallback + log entry" explicit at every call site.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

MAX_ERROR_CHARS = 300

# OpenAI error messages can echo part of the API key ("Incorrect API key provided: sk-...").
# Anything that looks like a key is replaced before it reaches a log file or the terminal.
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-*]{4,}")


def redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub("sk-***", text)


def describe_error(exc: BaseException) -> str:
    """Short, single-line, secret-free description of an exception for logs."""
    message = str(exc).replace("\n", " ").strip()
    text = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    return redact_secrets(text)[:MAX_ERROR_CHARS]


@dataclass(frozen=True)
class CallOutcome(Generic[T]):
    value: T | None
    error: str | None
    elapsed_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


def elapsed_ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


async def with_timeout(awaitable: Awaitable[T], timeout_s: float) -> T:
    """Await ``awaitable``; raises ``TimeoutError`` if it takes longer than ``timeout_s``.

    Use this everywhere instead of ``asyncio.wait_for``. On Python 3.11 ``wait_for`` throws a
    cancellation away when the awaited work has just finished, so a stop request from the
    experimenter could get lost (a WoZ command was applied 26 s late in a live run).
    ``asyncio.timeout`` does not have that problem.
    """
    async with asyncio.timeout(timeout_s):
        return await awaitable


async def timed_call(factory: Callable[[], Awaitable[T]], timeout_s: float) -> CallOutcome[T]:
    """Await ``factory()`` with a timeout. Errors and timeouts become a failed outcome."""
    start = time.perf_counter()
    try:
        value = await with_timeout(factory(), timeout_s)
    except TimeoutError:
        return CallOutcome(
            None, f"timeout after {timeout_s:g} s", elapsed_ms_since(start), timed_out=True
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # any failure of an external call -> fallback path, never a crash
        return CallOutcome(None, describe_error(exc), elapsed_ms_since(start))
    return CallOutcome(value, None, elapsed_ms_since(start))
