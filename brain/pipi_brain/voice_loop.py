"""The M1 voice loop: listen -> transcribe -> think (LLM JSON) -> speak, with full logging.

This is the turn logic only. Real or fake dependencies are passed in (``VoiceLoopDeps``), so
the whole loop is tested without network or audio hardware. Wiring of the real components
and the terminal UI live in ``voice_app.py``.

Robustness rules (docs/SYSTEM_DESIGN.md section 10):
- STT error / timeout / empty transcript -> "Sorry, could you say that again?" (fixed line)
- LLM error / invalid JSON / timeout     -> one retry -> scripted fallback line
- TTS error / timeout                    -> captions only (text printed, nothing played)
- Speaker error / timeout                -> captions only
- Microphone failure                     -> switch to typed input for the rest of the session
- Body (desktop pet) not connected / no ack -> laptop speaker plays the audio instead
Every failure is logged as an event; nothing is silently swallowed.

With a body (``--body pet``) Pipi's text is still printed in the terminal, the body shows
``listening`` eyes while waiting for the user and ``thinking`` eyes while the answer is
prepared, and speech (caption + audio + talking animation) happens on the body.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pipi_brain.bodies.base import Body
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.dialogue.prompts import ConversationTurn, PromptBody, build_messages
from pipi_brain.latency import TurnLatency, summarize_turns
from pipi_brain.logging_study import StudyLogger
from pipi_brain.memory import Memory, MemoryUpdates
from pipi_brain.protocol import Expression, EyeState
from pipi_brain.resilience import describe_error, elapsed_ms_since, timed_call
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.audio_input import AudioInput
from pipi_brain.speech.audio_utils import samples_to_wav
from pipi_brain.speech.base import (
    MicrophoneError,
    Speaker,
    SpeechAudio,
    SpeechToText,
    TextToSpeech,
    Utterance,
)

QUIT_COMMANDS = frozenset({"/quit", "/exit", "quit", "exit"})
LOG_BODY = "terminal"  # no body: the M1 terminal session


class TextInput(Protocol):
    async def read_line(self) -> str | None:
        """Next typed line, or None when the user quits (EOF)."""
        ...


@dataclass(frozen=True)
class VoiceLoopDeps:
    stt: SpeechToText
    tts: TextToSpeech
    speaker: Speaker
    dialogue: DialogueEngine
    text_input: TextInput
    audio_input: AudioInput | None  # None = typed input only
    body: Body | None = None  # None = terminal + laptop speaker only


@dataclass(frozen=True)
class VoiceLoopSettings:
    participant_id: str
    persona_id: str
    history_turns: int
    silence_reprompt_s: float
    stt_timeout_s: float
    tts_timeout_s: float
    playback_margin_s: float
    prompt_body: PromptBody = "desktop_pet"
    start_phase: str = "GREETING"
    log_body: str = LOG_BODY  # "body" field of every event (desktop_pet with --body pet)


@dataclass(frozen=True)
class _Silence:
    waited_s: float


@dataclass(frozen=True)
class _Typed:
    text: str


_QUIT = object()
UserInput = Utterance | _Typed | _Silence | object


@dataclass(frozen=True)
class _ReplyMeta:
    stt_ms: int | None = None
    llm_ms: int | None = None
    expression: Expression = "idle"
    gesture: str = "none"
    fallback: str | None = None
    line_id: str | None = None  # set for fixed (non-LLM) lines
    llm_attempts: int | None = None


class VoiceLoop:
    def __init__(
        self,
        *,
        deps: VoiceLoopDeps,
        settings: VoiceLoopSettings,
        content: DialogueContent,
        logger: StudyLogger,
        gate: AudioGate,
        emit: Callable[[str], None] = print,
    ) -> None:
        self._deps = deps
        self._settings = settings
        self._content = content
        self._logger = logger
        self._gate = gate
        self._emit = emit
        self._audio_input = deps.audio_input
        self._started = time.perf_counter()
        self.phase = settings.start_phase
        self.memory = Memory(participant_id=settings.participant_id, persona=settings.persona_id)
        self.history: tuple[ConversationTurn, ...] = ()
        self.latencies: tuple[TurnLatency, ...] = ()
        self.user_turns = 0

    @property
    def input_mode(self) -> Literal["voice", "typed"]:
        return "voice" if self._audio_input is not None else "typed"

    # --- main loop ------------------------------------------------------------------------

    async def run(self, max_user_turns: int | None = None) -> None:
        await self._say_fixed("opening")
        reprompted = False
        while max_user_turns is None or self.user_turns < max_user_turns:
            user_input = await self._next_input()
            if user_input is _QUIT:
                return
            if isinstance(user_input, _Silence):
                if not reprompted:
                    self._log("silence_reprompt", {"waited_s": user_input.waited_s})
                    await self._say_fixed("silence_reprompt")
                    reprompted = True
                continue
            reprompted = False
            if isinstance(user_input, Utterance):
                await self.handle_utterance(user_input)
            elif isinstance(user_input, _Typed):
                await self.handle_text(user_input.text)

    async def _next_input(self) -> UserInput:
        await self._set_eyes("listening")
        user_input = await self._wait_for_input()
        if isinstance(user_input, Utterance | _Typed):
            await self._set_eyes("thinking")  # show at once that Pipi is working on it
        return user_input

    async def _wait_for_input(self) -> UserInput:
        if self._audio_input is None:
            return await self._read_typed()
        self._emit("  (listening...)")
        try:
            utterance = await self._audio_input.listen(
                self._settings.silence_reprompt_s,
                on_speech_start=lambda: self._emit("  (hearing you...)"),
            )
        except MicrophoneError as exc:
            await self._switch_to_typed(exc)
            return await self._read_typed()
        if utterance is None:
            return _Silence(self._settings.silence_reprompt_s)
        return utterance

    async def _read_typed(self) -> UserInput:
        while True:
            line = await self._deps.text_input.read_line()
            if line is None or line.strip().lower() in QUIT_COMMANDS:
                return _QUIT
            if line.strip():
                return _Typed(line.strip())

    async def _switch_to_typed(self, exc: MicrophoneError) -> None:
        self._log(
            "audio_error",
            {"device": "microphone", "error": describe_error(exc), "fallback": "typed_input"},
        )
        self._emit(f"  [microphone problem: {exc}] -> please type instead (/quit to stop)")
        audio_input, self._audio_input = self._audio_input, None
        if audio_input is not None:
            try:
                await audio_input.microphone.close()
            except Exception as close_exc:  # closing a broken mic must not end the session
                self._log(
                    "audio_error", {"device": "microphone", "error": describe_error(close_exc)}
                )

    # --- one turn -------------------------------------------------------------------------

    async def handle_utterance(self, utterance: Utterance) -> None:
        start = time.perf_counter()
        wav = samples_to_wav(utterance.samples, utterance.sample_rate)
        stt = await timed_call(lambda: self._deps.stt.transcribe(wav), self._settings.stt_timeout_s)
        if not stt.ok:
            self._log(
                "stt_error",
                {"error": stt.error, "timed_out": stt.timed_out, "fallback": "stt_retry"},
            )
            await self._reply_fixed("stt_retry", start, stt_ms=stt.elapsed_ms, fallback="stt_error")
            return
        text = (stt.value or "").strip()
        if not text:
            self._log("clarification", {"reason": "empty_transcript"})
            await self._reply_fixed("stt_retry", start, stt_ms=stt.elapsed_ms, fallback="empty")
            return
        self._log_user_turn(
            text,
            input_mode="voice",
            stt_ms=stt.elapsed_ms,
            audio_ms=utterance.duration_ms,
            truncated=utterance.truncated,
        )
        await self._respond(text, start, stt_ms=stt.elapsed_ms)

    async def handle_text(self, text: str) -> None:
        start = time.perf_counter()
        self._log_user_turn(text, input_mode="typed")
        await self._respond(text, start, stt_ms=None)

    def _log_user_turn(self, text: str, *, input_mode: str, **extra: Any) -> None:
        self.user_turns += 1
        self._log("turn", {"speaker": "user", "text": text, "input": input_mode, **extra})
        if input_mode == "voice":
            self._emit(f"You: {text}")
        self.history = (*self.history, ConversationTurn("user", text))

    async def _respond(self, user_text: str, start: float, *, stt_ms: int | None) -> None:
        persona_id = self._settings.persona_id
        messages = build_messages(
            persona=self._content.persona(persona_id),
            body=self._settings.prompt_body,
            phase=self.phase,
            phase_instruction=self._content.phase_instruction(self.phase),
            memory=self.memory,
            history=self.history[:-1],  # the latest user line is sent as the user message
            history_turns=self._settings.history_turns,
            user_text=user_text,
        )
        result = await self._deps.dialogue.respond(
            messages, self._content.line("llm_fallback", persona_id)
        )
        for attempt, error in enumerate(result.errors, start=1):
            self._log(
                "llm_error",
                {
                    "error": error,
                    "attempt": attempt,
                    "retry": attempt < result.attempts,
                    "fallback": result.fallback_used and attempt == len(result.errors),
                },
            )
        self._remember(result.turn.memory_updates)
        meta = _ReplyMeta(
            stt_ms=stt_ms,
            llm_ms=result.llm_ms,
            expression=result.turn.expression,
            gesture=result.turn.gesture,
            fallback="llm_fallback" if result.fallback_used else None,
            llm_attempts=result.attempts,
        )
        await self._speak(result.turn.say, meta, start=start)
        self._maybe_advance_phase()

    def _remember(self, updates: MemoryUpdates) -> None:
        new_memory, changed = self.memory.apply(updates)
        if not changed:
            return
        self.memory = new_memory
        # Values stay out of events.jsonl (privacy): only memory.json holds e.g. the name.
        self._log("memory_update", {"fields": changed})
        self._logger.write_json("memory.json", self.memory.model_dump(mode="json"))

    def _maybe_advance_phase(self) -> None:
        if self.phase == "GREETING" and self.memory.greeting_complete:
            self._log("phase_change", {"from": "GREETING", "to": "CHAT", "trigger": "auto"})
            self.phase = "CHAT"

    # --- speaking -------------------------------------------------------------------------

    async def _say_fixed(self, line_id: str) -> None:
        """A fixed line not caused by user input (opening, re-prompt): no turn latency."""
        text = self._content.line(line_id, self._settings.persona_id)
        await self._speak(text, _ReplyMeta(line_id=line_id), start=None)

    async def _reply_fixed(
        self, line_id: str, start: float, *, stt_ms: int | None, fallback: str
    ) -> None:
        text = self._content.line(line_id, self._settings.persona_id)
        await self._speak(
            text, _ReplyMeta(stt_ms=stt_ms, line_id=line_id, fallback=fallback), start=start
        )

    async def _speak(self, text: str, meta: _ReplyMeta, *, start: float | None) -> None:
        self.history = (*self.history, ConversationTurn("pipi", text))
        tts = await timed_call(
            lambda: self._deps.tts.synthesize(text), self._settings.tts_timeout_s
        )
        if not tts.ok:
            self._log(
                "tts_error",
                {"error": tts.error, "timed_out": tts.timed_out, "fallback": "captions_only"},
            )
        data: dict[str, Any] = {
            "speaker": "pipi",
            "text": text,
            "tts_ms": tts.elapsed_ms,
            "expression": meta.expression,
            "gesture": meta.gesture,
            "fallback_used": meta.fallback,
            "audio": tts.ok,
        }
        if meta.line_id is not None:
            data["line_id"] = meta.line_id
        latency: TurnLatency | None = None
        if start is not None:
            latency = TurnLatency(meta.stt_ms, meta.llm_ms, tts.elapsed_ms, elapsed_ms_since(start))
            self.latencies = (*self.latencies, latency)
            data.update(stt_ms=meta.stt_ms, llm_ms=meta.llm_ms, total_ms=latency.total_ms)
            if meta.llm_attempts is not None:
                data["llm_attempts"] = meta.llm_attempts
        self._log("turn", data)

        self._emit(f"Pipi: {text}")
        if latency is not None:
            self._emit(f"  [latency] {latency.format()}")
        audio = tts.value if tts.ok else None
        if self._deps.body is not None:
            await self._speak_on_body(self._deps.body, text, audio, meta)
        elif audio is not None:
            await self._play(audio)

    async def _set_eyes(self, state: EyeState) -> None:
        """Eyes on the body, if there is one (failures are logged by the body)."""
        if self._deps.body is not None and self._deps.body.connected:
            await self._deps.body.set_eyes(state)

    async def _speak_on_body(
        self, body: Body, text: str, audio: SpeechAudio | None, meta: _ReplyMeta
    ) -> None:
        if meta.gesture != "none" and body.connected:
            await body.play_motion(meta.gesture)
        # Half-duplex: the mic ignores Pipi's own voice while the body plays it.
        gate: AbstractContextManager[None] = (
            self._gate.speaking() if audio is not None else nullcontext()
        )
        with gate:
            result = await body.speak(text, audio, meta.expression)
        if result.delivered:
            return
        fallback = "local_speaker" if audio is not None else "captions_only"
        self._log(
            "body_fallback",
            {"body": body.name, "action": "speak", "error": result.error, "fallback": fallback},
        )
        self._emit(f"  [{body.name}: {result.error}] -> {fallback.replace('_', ' ')}")
        if audio is not None:
            await self._play(audio)

    async def _play(self, audio: SpeechAudio) -> None:
        timeout_s = audio.duration_s + self._settings.playback_margin_s
        with self._gate.speaking():  # half-duplex: the mic ignores Pipi's own voice
            outcome = await timed_call(lambda: self._deps.speaker.play(audio), timeout_s)
            if outcome.timed_out:
                self._deps.speaker.stop()
        if not outcome.ok:
            self._log(
                "audio_error",
                {"device": "speaker", "error": outcome.error, "fallback": "captions_only"},
            )
            self._emit(f"  [speaker problem: {outcome.error}] (captions only)")

    # --- end of session -------------------------------------------------------------------

    def summary(self, reason: str) -> dict[str, Any]:
        events = self._logger.read_events()
        counts: dict[str, int] = {}
        for event in events:
            counts[event["type"]] = counts.get(event["type"], 0) + 1
        return {
            "session": self._logger.session_id,
            "end_reason": reason,
            "duration_ms": elapsed_ms_since(self._started),
            "user_turns": self.user_turns,
            "final_phase": self.phase,
            "input_mode": self.input_mode,
            "event_counts": counts,
            "latency": summarize_turns(self.latencies),
        }

    def finalize(self, reason: str) -> dict[str, Any]:
        """Log session_end and write memory.json + summary.json. Safe to call once at exit."""
        summary = self.summary(reason)
        self._log(
            "session_end",
            {
                "reason": reason,
                "duration_ms": summary["duration_ms"],
                "user_turns": summary["user_turns"],
                "latency": summary["latency"],
            },
        )
        self._logger.write_json("memory.json", self.memory.model_dump(mode="json"))
        self._logger.write_json("summary.json", summary)
        return summary

    def _log(self, event_type: str, data: dict[str, Any]) -> None:
        self._logger.log(event_type, data, phase=self.phase, body=self._settings.log_body)
