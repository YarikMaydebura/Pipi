"""The full study session: body server + SessionController (+ optional WoZ panel server).

Started by ``python -m pipi_brain --config ../config/dev.yaml --session [--typed]``.

What runs:
- the body WebSocket server (desktop pet + fake robot, ``BodyServer.from_config``),
- the ``SessionController`` (phases/), speaking through the active body, with the laptop
  speaker as fallback, and the TTS disk cache for fixed lines,
- the terminal: participant input when ``--typed``, and ``/commands`` for the experimenter,
- the WoZ panel server, if a ``woz_server_factory`` is given: called as
  ``factory(controller, log=study_log)`` and used as an async context manager, so
  ``functools.partial(woz_server.serve_woz, loaded=loaded)`` plugs in as it is.
  Without a panel the session starts by itself after SETUP.

Every factory can be replaced by fakes; that is how the tests run whole sessions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from pipi_brain.bodies.alpha_mini import AlphaMiniBody, AlphaMiniSettings
from pipi_brain.bodies.alpha_mini_moves import MoveLibrary, load_moves
from pipi_brain.bodies.base import Body
from pipi_brain.bodies.ridk import RidkConnector
from pipi_brain.config import ConfigError, LoadedConfig
from pipi_brain.dialogue.content import load_dialogue_content
from pipi_brain.games.motions import MotionLibrary
from pipi_brain.games.setup import check_session, load_game_setup
from pipi_brain.logging_study import StudyLogger
from pipi_brain.phases.clock import Clock, RealClock
from pipi_brain.phases.controller import SessionController, SessionDeps
from pipi_brain.phases.flow import Directive
from pipi_brain.phases.inputs import TerminalSessionInput
from pipi_brain.phases.terminal_commands import parse_terminal_command
from pipi_brain.resilience import describe_error
from pipi_brain.server import BodyServer, BodyServerError
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.bang import MicBangDetector
from pipi_brain.speech.tts_cache import TtsCache
from pipi_brain.voice_app import DepsFactory, SessionOptions, build_real_deps
from pipi_brain.woz_api import WozBackend

EventLog = Callable[[str, Mapping[str, Any]], None]
LogFor = Callable[[str], EventLog]


class WozServerFactory(Protocol):
    """Starts the WoZ panel server for ``backend``; ``log`` writes to this session's log."""

    def __call__(
        self, backend: WozBackend, *, log: EventLog
    ) -> AbstractAsyncContextManager[Any]: ...


class BodyHost(Protocol):
    """What the session needs from the body server: its bodies, start and stop."""

    @property
    def bodies(self) -> Mapping[str, Body]: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


BodyHostFactory = Callable[
    [LoadedConfig, Callable[[str, Mapping[str, Any]], None], LogFor], BodyHost
]


@dataclass(frozen=True)
class SessionAppOptions:
    participant_id: str = "DEV"
    persona_id: str | None = None  # set = fixed persona, no PERSONA_PICK question
    typed_input: bool = False
    auto_start: bool | None = None  # None = start by itself when there is no WoZ panel


class RobotBodyHost:
    """The WebSocket body server (pet + fake robot) plus the real Alpha Mini over RidK."""

    def __init__(self, server: BodyHost, robot: AlphaMiniBody, connector: RidkConnector) -> None:
        self._server = server
        self._connector = connector
        self._bodies: Mapping[str, Body] = MappingProxyType({**server.bodies, robot.name: robot})

    @property
    def bodies(self) -> Mapping[str, Body]:
        return self._bodies

    async def start(self) -> None:
        await self._server.start()  # BodyServerError -> the caller falls back (no robot either)
        await self._connector.start()  # returns at once; connects in the background

    async def stop(self) -> None:
        await self._connector.stop()
        await self._server.stop()


def load_robot_moves(loaded: LoadedConfig, motions: MotionLibrary) -> MoveLibrary:
    """alpha_mini.yaml, checked against motions.yaml. Raises ConfigError."""
    moves = load_moves(loaded.app.robot.moves_file)
    used = (motions.resolve(name, AlphaMiniBody.name) for name in motions.names)
    if missing := moves.missing(name for name in used if name is not None):
        raise ConfigError(
            f"motions.yaml names Alpha Mini moves that are not in "
            f"{loaded.app.robot.moves_file}: {', '.join(missing)}"
        )
    return moves


def default_body_host(
    loaded: LoadedConfig, log: Callable[[str, Mapping[str, Any]], None], log_for: LogFor
) -> BodyHost:
    """Pet + fake robot always; the real Alpha Mini too when RIDK_REALM is set."""
    app = loaded.app
    server = BodyServer.from_config(app, log=log, log_for=log_for)
    realm = loaded.secrets.ridk_realm
    if realm is None:
        return server
    moves = load_robot_moves(loaded, load_game_setup(app.games).motions)
    robot_log = log_for(AlphaMiniBody.name)
    settings = AlphaMiniSettings(
        call_timeout_s=app.robot.ridk_call_timeout_s,
        stop_timeout_s=app.bodies.stop_timeout_s,
        speech_s_per_char=app.bodies.caption_s_per_char,
    )
    robot = AlphaMiniBody(moves, settings, log=robot_log)
    connector = RidkConnector(app.robot.ridk_url, realm.get_secret_value(), robot, log=robot_log)
    return RobotBodyHost(server, robot, connector)


async def run_session(
    loaded: LoadedConfig,
    options: SessionAppOptions = SessionAppOptions(),
    *,
    woz_server_factory: WozServerFactory | None = None,
    deps_factory: DepsFactory = build_real_deps,
    body_host_factory: BodyHostFactory = default_body_host,
    clock: Clock | None = None,
    emit: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run one full session; returns the summary. Raises ConfigError on bad content."""
    app = loaded.app
    if options.persona_id is not None:
        app = app.model_copy(
            update={
                "persona": app.persona.model_copy(
                    update={"default": options.persona_id, "allow_choice": False}
                )
            }
        )
    content = load_dialogue_content(app.dialogue)
    content.persona(app.persona.default)  # unknown persona -> ConfigError before anything starts
    reading_text = _read_reading_text(app.session.reading_text_file)
    game_setup = load_game_setup(app.games)  # games.yaml + motions.yaml: ConfigError if wrong
    check_session(game_setup, app.session)
    if loaded.secrets.ridk_realm is not None:  # the real robot will be used: check its moves now
        load_robot_moves(loaded, game_setup.motions)

    gate = AudioGate(app.audio.gate_tail_ms)
    voice_options = SessionOptions(
        participant_id=options.participant_id, typed_input=options.typed_input
    )
    deps, health = await deps_factory(loaded, voice_options, gate)
    # The duel's bang detector reads raw frames of the same microphone (never the audio gate).
    bang_detector = (
        MicBangDetector(
            deps.audio_input.microphone,
            threshold_db=game_setup.config.quick_draw.bang_threshold_db,
            frame_timeout_s=app.audio.mic_frame_timeout_s,
        )
        if deps.audio_input is not None
        else None
    )
    health["bang_detector"] = (
        f"ok (threshold {game_setup.config.quick_draw.bang_threshold_db:g} dBFS)"
        if bang_detector is not None
        else "not used (no microphone): typing + Enter is the bang"
    )
    logger = StudyLogger(app.logging.dir, options.participant_id)
    ref: dict[str, SessionController] = {}

    def phase() -> str | None:
        return ref["ctl"].state.phase if "ctl" in ref else "SETUP"

    def log(event_type: str, data: Mapping[str, Any]) -> None:
        logger.log(event_type, data, phase=phase())

    def log_for(body: str) -> Callable[[str, Mapping[str, Any]], None]:
        return lambda event_type, data: logger.log(event_type, data, phase=phase(), body=body)

    host = body_host_factory(loaded, log, log_for)
    tts_cache = (
        TtsCache(
            app.tts_cache.dir,
            tts=deps.tts,
            model=app.models.tts,
            voice=app.models.tts_voice,
            timeout_s=app.timeouts.tts_s,
            on_error=log,
        )
        if app.tts_cache.enabled
        else None
    )

    async def on_command(line: str) -> None:
        parsed = parse_terminal_command(line)
        if isinstance(parsed, str):
            emit(parsed)
            return
        outcome = await ref["ctl"].handle_woz(parsed)
        emit(f"  [woz] {parsed.command}: {'ok' if outcome.ok else outcome.error}")

    def on_quit() -> None:
        ref["ctl"].enqueue(Directive("goto", "END", trigger="user", command="terminal_eof"))

    session_input = TerminalSessionInput(
        audio_input=deps.audio_input,
        text_input=deps.text_input,
        on_command=on_command,
        on_quit=on_quit,
        log=log,
        alert=lambda level, message: ref["ctl"].events.alert(level, message),
        emit=emit,
    )
    auto_start = (
        options.auto_start if options.auto_start is not None else woz_server_factory is None
    )
    controller = SessionController(
        app=app,
        content=content,
        logger=logger,
        deps=SessionDeps(
            stt=deps.stt,
            tts=deps.tts,
            speaker=deps.speaker,
            dialogue=deps.dialogue,
            input=session_input,
            bodies=host.bodies,
            gate=gate,
            clock=clock or RealClock(),
            tts_cache=tts_cache,
            bang_detector=bang_detector,
        ),
        participant_id=options.participant_id,
        auto_start=auto_start,
        game_setup=game_setup,
        reading_text=reading_text,
        start_data={
            "config_hash": loaded.config_hash,
            "components": health,
            "persona_fixed": options.persona_id is not None,
            "woz_panel": woz_server_factory is not None,
            "models": {
                "dialogue": app.models.dialogue,
                "stt": app.models.stt,
                "tts": app.models.tts,
                "tts_voice": app.models.tts_voice,
                "reasoning_effort": app.dialogue.reasoning_effort,
            },
        },
        emit=emit,
    )
    ref["ctl"] = controller
    emit(f"Session {logger.session_id}  (log: {logger.folder})")
    for component, status in health.items():
        emit(f"  {component:<13}: {status}")
    controller.log_session_start()  # first event, before the servers log anything
    async with AsyncExitStack() as stack:
        stack.push_async_callback(_close_audio, deps, session_input)
        await _start_bodies(host, controller, stack, emit)
        if woz_server_factory is not None:
            await _start_woz(woz_server_factory, controller, stack, log, emit)
        if auto_start:
            await _wait_for_pet(host, app.bodies.connect_wait_s, emit)
        session_input.start()
        emit(
            "Type /help for experimenter commands."
            + (" Type to Pipi." if options.typed_input else "")
        )
        summary = await controller.run()
    emit(f"Session ended ({summary['end_reason']}). Log: {logger.folder}")
    return summary


def _read_reading_text(path: Any) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        raise ConfigError(f"Cannot read session.reading_text_file {path}: {exc}") from exc


async def _start_bodies(
    host: BodyHost,
    controller: SessionController,
    stack: AsyncExitStack,
    emit: Callable[[str], None],
) -> None:
    try:
        await host.start()
    except BodyServerError as exc:
        controller.events.alert("error", f"Body server failed ({exc}): laptop speaker only.")
        emit(f"  [body server: {exc}] -> laptop speaker only")
        return
    stack.push_async_callback(host.stop)


async def _start_woz(
    factory: WozServerFactory,
    controller: SessionController,
    stack: AsyncExitStack,
    log: EventLog,
    emit: Callable[[str], None],
) -> None:
    try:
        await stack.enter_async_context(factory(controller, log=log))
    except Exception as exc:  # no panel is bad, but the typed /commands still work
        controller.events.alert("error", f"WoZ panel server failed: {describe_error(exc)}")
        emit(f"  [WoZ panel failed: {describe_error(exc)}] -> use /commands in this terminal")


async def _wait_for_pet(host: BodyHost, timeout_s: float, emit: Callable[[str], None]) -> None:
    pet = host.bodies.get("desktop_pet")
    if pet is None or pet.connected:
        return
    emit(f"Waiting up to {timeout_s:g} s for the desktop pet ...")
    if not await pet.wait_connected(timeout_s):
        emit("  no desktop pet yet: continuing (it can connect at any time).")


async def _close_audio(deps: Any, session_input: TerminalSessionInput) -> None:
    deps.speaker.stop()
    await session_input.close()
