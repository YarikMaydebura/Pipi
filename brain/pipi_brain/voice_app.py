"""Terminal voice session: builds the real components and runs the VoiceLoop.

Started by ``python -m pipi_brain --config ../config/dev.yaml --voice-loop``.
``--body pet`` also starts the body WebSocket server and speaks through the desktop pet
(laptop speaker as fallback when the pet is missing).
``deps_factory`` can be swapped for fakes, which is how the tests run a full session.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from pipi_brain.bodies.desktop_pet import DesktopPetBody
from pipi_brain.config import AppConfig, ConfigError, LoadedConfig
from pipi_brain.dialogue.content import DialogueContent, load_dialogue_content
from pipi_brain.dialogue.llm import DialogueEngine, OpenAIChatModel
from pipi_brain.logging_study import StudyLogger
from pipi_brain.openai_client import create_openai_client
from pipi_brain.server import BodyServer, BodyServerError
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.audio_input import AudioInput
from pipi_brain.speech.base import MicrophoneError
from pipi_brain.speech.devices import SoundDeviceMicrophone, SoundDeviceSpeaker
from pipi_brain.speech.segmenter import UtteranceSegmenter
from pipi_brain.speech.stt import OpenAISpeechToText
from pipi_brain.speech.tts import OpenAITextToSpeech
from pipi_brain.speech.vad import create_vad
from pipi_brain.voice_loop import VoiceLoop, VoiceLoopDeps, VoiceLoopSettings


@dataclass(frozen=True)
class SessionOptions:
    participant_id: str = "DEV"
    persona_id: str | None = None  # None = config persona.default
    typed_input: bool = False  # type instead of speaking (no microphone, no STT)
    max_user_turns: int | None = None
    body: Literal["terminal", "pet"] = "terminal"  # "pet": speak through the desktop pet


Health = dict[str, str]
DepsFactory = Callable[
    [LoadedConfig, SessionOptions, AudioGate], Awaitable[tuple[VoiceLoopDeps, Health]]
]


class TerminalTextInput:
    """Reads typed lines without blocking the event loop.

    A daemon thread is used instead of ``asyncio.to_thread`` so that Ctrl+C can end the
    program even while ``input()`` is waiting (the default executor would wait for it).
    """

    def __init__(self, prompt: str = "You: ") -> None:
        self._prompt = prompt

    async def read_line(self) -> str | None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str | None] = loop.create_future()

        def worker() -> None:
            try:
                line: str | None = input(self._prompt)
            except EOFError:
                line = None
            if not future.done():
                loop.call_soon_threadsafe(_set_if_pending, future, line)

        threading.Thread(target=worker, name="typed-input", daemon=True).start()
        return await future


def _set_if_pending(future: asyncio.Future[str | None], value: str | None) -> None:
    if not future.done():
        future.set_result(value)


async def build_real_deps(
    loaded: LoadedConfig, options: SessionOptions, gate: AudioGate
) -> tuple[VoiceLoopDeps, Health]:
    app = loaded.app
    api_key = loaded.secrets.openai_api_key
    if api_key is None:
        raise ConfigError("OPENAI_API_KEY is missing (copy .env.example to .env and fill it in)")
    client = create_openai_client(api_key)
    chat_model = OpenAIChatModel(
        client,
        model=app.models.dialogue,
        reasoning_effort=app.dialogue.reasoning_effort,
        max_output_tokens=app.dialogue.max_output_tokens,
    )
    health: Health = {"openai_key": "set", "speaker": "not checked before first playback"}
    audio_input: AudioInput | None = None
    if options.typed_input:
        health["microphone"] = "not used (typed input)"
        health["vad"] = "not used (typed input)"
    else:
        audio_input = await _open_audio_input(app, gate, health)
    deps = VoiceLoopDeps(
        stt=OpenAISpeechToText(client, model=app.models.stt),
        tts=OpenAITextToSpeech(client, model=app.models.tts, voice=app.models.tts_voice),
        speaker=SoundDeviceSpeaker(device=app.audio.output_device),
        dialogue=DialogueEngine(
            chat_model, timeout_s=app.timeouts.llm_s, retries=app.dialogue.llm_retries
        ),
        text_input=TerminalTextInput(),
        audio_input=audio_input,
    )
    return deps, health


async def _open_audio_input(app: AppConfig, gate: AudioGate, health: Health) -> AudioInput | None:
    """Mic + VAD. Failures are recorded in ``health`` and lead to typed input, not a crash."""
    audio = app.audio
    choice = await asyncio.to_thread(
        create_vad, app.vad, sample_rate=audio.sample_rate, frame_samples=audio.frame_samples
    )
    health["vad"] = (
        choice.vad.name
        if choice.fallback_reason is None
        else f"{choice.vad.name} (fallback: {choice.fallback_reason})"
    )
    microphone = SoundDeviceMicrophone(
        sample_rate=audio.sample_rate, frame_samples=audio.frame_samples, device=audio.input_device
    )
    try:
        await microphone.start()
    except MicrophoneError as exc:
        health["microphone"] = f"failed ({exc}); using typed input"
        return None
    health["microphone"] = "ok"
    return AudioInput(
        microphone=microphone,
        vad=choice.vad,
        segmenter=UtteranceSegmenter(
            app.vad, sample_rate=audio.sample_rate, frame_samples=audio.frame_samples
        ),
        gate=gate,
        frame_timeout_s=audio.mic_frame_timeout_s,
    )


def _session_start_data(
    loaded: LoadedConfig,
    persona_id: str,
    persona_options: list[str],
    input_mode: str,
    output_body: str,
) -> dict[str, Any]:
    app = loaded.app
    return {
        "mode": app.mode,
        "config_hash": loaded.config_hash,
        "runner": "voice_loop_terminal",
        "input": input_mode,
        "output_body": output_body,
        "robot_side": app.pet.robot_side,
        "persona": persona_id,
        "persona_options": persona_options,
        "models": {
            "dialogue": app.models.dialogue,
            "stt": app.models.stt,
            "tts": app.models.tts,
            "tts_voice": app.models.tts_voice,
            "reasoning_effort": app.dialogue.reasoning_effort,
        },
        "cue_checklist": app.cues.model_dump(),
    }


async def run_voice_session(
    loaded: LoadedConfig,
    options: SessionOptions,
    *,
    deps_factory: DepsFactory = build_real_deps,
    emit: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run one terminal session; returns the summary. Raises ConfigError on bad content."""
    app = loaded.app
    content = load_dialogue_content(app.dialogue)
    persona_id = options.persona_id or app.persona.default
    content.persona(persona_id)  # unknown persona -> ConfigError before anything starts

    gate = AudioGate(app.audio.gate_tail_ms)
    deps, health = await deps_factory(loaded, options, gate)
    logger = StudyLogger(app.logging.dir, options.participant_id)
    input_mode = "voice" if deps.audio_input is not None else "typed"
    output_body = "desktop_pet" if options.body == "pet" else "terminal"
    logger.log(
        "session_start",
        _session_start_data(loaded, persona_id, list(content.personas), input_mode, output_body),
    )
    emit(f"Session {logger.session_id}  (log: {logger.folder})")
    phase_ref: dict[str, VoiceLoop] = {}

    def body_log(event_type: str, data: Mapping[str, Any]) -> None:
        loop = phase_ref.get("loop")
        logger.log(event_type, data, phase=loop.phase if loop else None, body=output_body)

    async with _maybe_pet(app, options, body_log, emit) as pet:
        if pet is not None:
            deps = dataclasses.replace(deps, body=pet)
            health["desktop_pet"] = pet.health()
            health["speaker"] = "fallback only (the pet plays the audio)"
        elif options.body == "pet":
            health["desktop_pet"] = "server failed; terminal + laptop speaker"
        logger.log("health_check", health)
        method = "cli" if options.persona_id else "config_default"
        logger.log("persona_choice", {"persona": persona_id, "method": method})
        for component, status in health.items():
            emit(f"  {component:<11}: {status}")
        if input_mode == "voice":
            emit("Talk to Pipi. Press Ctrl+C to stop.")
        else:
            emit("Type to Pipi. Type /quit (or Ctrl+C) to stop.")
        return await _run_loop(
            app, options, deps, persona_id, content, logger, gate, emit, phase_ref, output_body
        )


@asynccontextmanager
async def _maybe_pet(
    app: AppConfig,
    options: SessionOptions,
    log: Callable[[str, Mapping[str, Any]], None],
    emit: Callable[[str], None],
) -> AsyncIterator[DesktopPetBody | None]:
    """With ``--body pet``: run the body server and wait (a while) for the pet to connect."""
    if options.body != "pet":
        yield None
        return
    pet = DesktopPetBody(app.bodies, robot_side=app.pet.robot_side, log=log)
    server = BodyServer(
        host=app.server.host,
        port=app.server.port,
        bodies={"desktop_pet": pet},
        hello_timeout_s=app.bodies.hello_timeout_s,
        log=log,
    )
    try:
        await server.start()
    except BodyServerError as exc:
        log("body_error", {"error": str(exc), "fallback": "terminal_and_local_speaker"})
        emit(f"  [body server: {exc}] -> terminal + laptop speaker only")
        yield None
        return
    try:
        emit(
            f"Waiting up to {app.bodies.connect_wait_s:g} s for the desktop pet on {server.url} ..."
        )
        if await pet.wait_connected(app.bodies.connect_wait_s):
            emit("  desktop pet connected.")
        else:
            emit("  no desktop pet yet: continuing; it can still connect at any time.")
        yield pet
    finally:
        await server.stop()


async def _run_loop(
    app: AppConfig,
    options: SessionOptions,
    deps: VoiceLoopDeps,
    persona_id: str,
    content: DialogueContent,
    logger: StudyLogger,
    gate: AudioGate,
    emit: Callable[[str], None],
    phase_ref: dict[str, VoiceLoop],
    output_body: str,
) -> dict[str, Any]:
    settings = VoiceLoopSettings(
        participant_id=options.participant_id,
        persona_id=persona_id,
        history_turns=app.dialogue.history_turns,
        silence_reprompt_s=app.timers.silence_reprompt_s,
        stt_timeout_s=app.timeouts.stt_s,
        tts_timeout_s=app.timeouts.tts_s,
        playback_margin_s=app.timeouts.playback_margin_s,
        log_body=output_body,
    )
    loop = VoiceLoop(
        deps=deps, settings=settings, content=content, logger=logger, gate=gate, emit=emit
    )
    phase_ref["loop"] = loop
    reason = "interrupted"
    try:
        await loop.run(options.max_user_turns)
        reason = "completed"
    finally:
        summary = loop.finalize(reason)
        deps.speaker.stop()
        if deps.audio_input is not None:
            await deps.audio_input.microphone.close()
        emit(f"Session ended ({reason}). Log: {logger.folder}")
    return summary
