"""Where the participant's words come from: the microphone, or lines typed in the terminal.

``UserInputSource`` is what the conversation code uses: ``next_input()`` waits for one
utterance (or typed line) and can be cancelled at any time; ``hearing`` is True while the
participant is in the middle of speaking (so a silence timer does not cut them off).

``TerminalSessionInput`` is the real one. It also reads the terminal all the time: lines that
start with ``/`` are experimenter commands (``/next``, ``/goto CHAT``, ...; see
``terminal_commands.py``), so a session can be driven without the WoZ panel. If the
microphone fails, input switches to typing for the rest of the session (logged).
Tests use ``fakes.FakeUserInput``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pipi_brain.resilience import describe_error
from pipi_brain.speech.audio_input import AudioInput
from pipi_brain.speech.base import MicrophoneError, Utterance
from pipi_brain.voice_loop import TextInput

InputMode = Literal["voice", "typed"]


@dataclass(frozen=True)
class TypedLine:
    text: str


UserInput = Utterance | TypedLine


class UserInputSource(Protocol):
    @property
    def mode(self) -> InputMode: ...

    @property
    def hearing(self) -> bool: ...

    async def next_input(self) -> UserInput: ...


class TerminalSessionInput:
    def __init__(
        self,
        *,
        audio_input: AudioInput | None,
        text_input: TextInput,
        on_command: Callable[[str], Awaitable[None]],
        on_quit: Callable[[], None],
        log: Callable[[str, Mapping[str, Any]], None],
        alert: Callable[[Literal["info", "warning", "error"], str], None],
        emit: Callable[[str], None] = print,
    ) -> None:
        self._audio_input = audio_input
        self._text_input = text_input
        self._on_command = on_command
        self._on_quit = on_quit
        self._log = log
        self._alert = alert
        self._emit = emit
        self._typed: asyncio.Queue[TypedLine] = asyncio.Queue()
        self._hearing = False
        self._reader: asyncio.Task[None] | None = None

    @property
    def mode(self) -> InputMode:
        return "voice" if self._audio_input is not None else "typed"

    @property
    def hearing(self) -> bool:
        return self._hearing

    def start(self) -> None:
        if self._reader is None:
            self._reader = asyncio.ensure_future(self._read_terminal())

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        if self._audio_input is not None:
            with contextlib.suppress(Exception):
                await self._audio_input.microphone.close()

    async def next_input(self) -> UserInput:
        if self._audio_input is not None:
            try:
                return await self._listen(self._audio_input)
            except MicrophoneError as exc:
                await self._switch_to_typed(exc)
        return await self._typed.get()

    async def _listen(self, audio_input: AudioInput) -> Utterance:
        def heard() -> None:
            self._hearing = True

        try:
            while True:
                utterance = await audio_input.listen(None, on_speech_start=heard)
                if utterance is not None:
                    return utterance
        finally:
            self._hearing = False

    async def _switch_to_typed(self, exc: MicrophoneError) -> None:
        self._log(
            "audio_error",
            {"device": "microphone", "error": describe_error(exc), "fallback": "typed_input"},
        )
        self._alert("warning", "Microphone failed: the participant has to type now.")
        self._emit(f"  [microphone problem: {exc}] -> please type instead")
        audio_input, self._audio_input = self._audio_input, None
        if audio_input is not None:
            try:
                await audio_input.microphone.close()
            except Exception as close_exc:  # a broken mic must not end the session
                self._log(
                    "audio_error", {"device": "microphone", "error": describe_error(close_exc)}
                )

    async def _read_terminal(self) -> None:
        while True:
            line = await self._text_input.read_line()
            if line is None:  # EOF / Ctrl+D
                if self.mode == "typed":
                    self._on_quit()
                return
            text = line.strip()
            if text.startswith("/"):
                await self._on_command(text)
            elif self.mode == "typed":
                # An empty line (just Enter) is passed on too: it is the "bang" of the duel.
                # Everything else ignores it (conversation.listen, allow_empty=False).
                self._typed.put_nowait(TypedLine(text))
            elif not text:
                continue
            else:
                self._emit("  (voice mode: speak to Pipi; type /help for experimenter commands)")
