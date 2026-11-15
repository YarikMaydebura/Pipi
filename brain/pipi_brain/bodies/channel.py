"""One WebSocket body's connection: send commands, match ``ack`` / ``speech_done`` by message id.

The channel is transport-agnostic: it talks to a ``BodyLink`` (the real one wraps a
WebSocket connection, tests use a fake). Every message in and out is logged as
``body_message`` (audio is never logged, only whether there was any); every failure is
logged as ``body_error``. Nothing here raises on a missing or slow body.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from pipi_brain.bodies.base import NOT_CONNECTED, BodyLog, BodyResult
from pipi_brain.protocol import (
    Ack,
    BodyToBrain,
    BrainToBody,
    Hello,
    SpeechDone,
    encode,
)
from pipi_brain.resilience import describe_error


class BodyLink(Protocol):
    """A live connection to one body (a WebSocket in the real app)."""

    description: str  # e.g. the remote address, for logs

    async def send(self, text: str) -> None: ...

    async def close(self) -> None: ...


class BodyDisconnectedError(Exception):
    """The body went away while the brain was waiting for its answer."""


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def summarize_outgoing(message: BrainToBody) -> dict[str, Any]:
    """Log-friendly view of a message: no timestamp, and audio replaced by a flag."""
    data = message.model_dump(mode="json", exclude={"ts"})
    if "audio_b64" in data:
        audio = data.pop("audio_b64")
        data["has_audio"] = bool(audio)
    return data


class BodyChannel:
    def __init__(self, body_name: str, log: BodyLog) -> None:
        self.body_name = body_name
        self._log = log
        self._link: BodyLink | None = None
        self._version: str | None = None
        self._connected = asyncio.Event()
        self._acks: dict[str, asyncio.Future[Ack]] = {}
        self._speech_done: dict[str, asyncio.Future[SpeechDone]] = {}

    # --- connection ------------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._link is not None

    @property
    def version(self) -> str | None:
        return self._version

    async def wait_connected(self, timeout_s: float) -> bool:
        if self.connected:
            return True
        try:
            await asyncio.wait_for(self._connected.wait(), timeout_s)
        except TimeoutError:
            return False
        return self.connected

    def attach(self, link: BodyLink, hello: Hello) -> BodyLink | None:
        """Use ``link`` from now on. Returns the previous link (the caller closes it)."""
        previous = self._link
        if previous is not None:
            self._fail_pending("replaced by a new connection")
            self._log(
                "body_disconnected",
                {"remote": previous.description, "reason": "replaced by a new connection"},
            )
        self._link = link
        self._version = hello.version
        self._connected.set()
        self._log("body_connected", {"remote": link.description, "version": hello.version})
        return previous

    def detach(self, link: BodyLink, reason: str) -> None:
        if link is not self._link:
            return  # an old, already replaced connection closing late
        self._link = None
        self._connected.clear()
        self._fail_pending(reason)
        self._log("body_disconnected", {"remote": link.description, "reason": reason})

    def _fail_pending(self, reason: str) -> None:
        futures: list[asyncio.Future[Any]] = [*self._acks.values(), *self._speech_done.values()]
        for future in futures:
            if not future.done():
                future.set_exception(BodyDisconnectedError(reason))
        self._acks.clear()
        self._speech_done.clear()

    # --- incoming --------------------------------------------------------------------------

    def receive(self, message: BodyToBrain) -> None:
        """Route a message from the body (already validated) to whoever waits for it."""
        data = message.model_dump(mode="json", exclude={"ts"})
        self._log("body_message", {"direction": "in", **data})
        if isinstance(message, Ack):
            ack_future = self._acks.pop(message.ref_id, None)
            if ack_future is not None and not ack_future.done():
                ack_future.set_result(message)
        elif isinstance(message, SpeechDone):
            done_future = self._speech_done.pop(message.ref_id, None)
            if done_future is not None and not done_future.done():
                done_future.set_result(message)

    # --- outgoing --------------------------------------------------------------------------

    def expect_speech_done(self, ref_id: str) -> asyncio.Future[SpeechDone]:
        """Register interest in ``speech_done`` BEFORE sending (it can arrive very quickly)."""
        future: asyncio.Future[SpeechDone] = asyncio.get_running_loop().create_future()
        self._speech_done[ref_id] = future
        return future

    def forget_speech_done(self, ref_id: str) -> None:
        future = self._speech_done.pop(ref_id, None)
        if future is not None and not future.done():
            future.cancel()

    async def request(
        self, message: BrainToBody, *, timeout_s: float, retries: int = 0
    ) -> BodyResult:
        """Send ``message`` and wait for its ack. Never raises (except on cancellation)."""
        start = time.perf_counter()
        error = NOT_CONNECTED
        timed_out = False
        for attempt in range(retries + 1):
            error, timed_out = await self._send_and_wait_ack(message, timeout_s)
            if not error:
                return BodyResult(ok=True, elapsed_ms=_ms_since(start))
            retry = attempt < retries and error != NOT_CONNECTED and timed_out
            self._log_error(message, error, timed_out=timed_out, retry=retry, attempt=attempt + 1)
            if not retry:
                break
        return BodyResult(ok=False, error=error, elapsed_ms=_ms_since(start), timed_out=timed_out)

    async def _send_and_wait_ack(self, message: BrainToBody, timeout_s: float) -> tuple[str, bool]:
        """Returns (error, timed_out); error is '' on success."""
        link = self._link
        if link is None:
            return NOT_CONNECTED, False
        future: asyncio.Future[Ack] = asyncio.get_running_loop().create_future()
        self._acks[message.id] = future
        try:
            self._log("body_message", {"direction": "out", **summarize_outgoing(message)})
            await asyncio.wait_for(link.send(encode(message)), timeout_s)
            ack = await asyncio.wait_for(future, timeout_s)
        except TimeoutError:
            return f"no ack within {timeout_s:g} s", True
        except BodyDisconnectedError as exc:
            return f"disconnected: {exc}", False
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a broken socket must not end the session
            return f"send failed: {describe_error(exc)}", False
        finally:
            if self._acks.get(message.id) is future:
                del self._acks[message.id]
        if not ack.ok:
            return f"body refused: {ack.error or 'no reason given'}", False
        return "", False

    async def wait_speech_done(
        self, ref_id: str, future: asyncio.Future[SpeechDone], timeout_s: float
    ) -> tuple[SpeechDone | None, str | None]:
        """Wait for ``speech_done``; returns (message, None) or (None, error)."""
        try:
            return await asyncio.wait_for(future, timeout_s), None
        except TimeoutError:
            return None, f"no speech_done within {timeout_s:g} s"
        except BodyDisconnectedError as exc:
            return None, f"disconnected: {exc}"
        finally:
            self.forget_speech_done(ref_id)

    def log_speak_error(self, ref_id: str, error: str) -> None:
        self._log(
            "body_error",
            {"message_type": "speak", "ref_id": ref_id, "error": error, "retry": False},
        )

    def _log_error(
        self, message: BrainToBody, error: str, *, timed_out: bool, retry: bool, attempt: int
    ) -> None:
        self._log(
            "body_error",
            {
                "message_type": message.type,
                "ref_id": message.id,
                "error": error,
                "timed_out": timed_out,
                "attempt": attempt,
                "retry": retry,
            },
        )
