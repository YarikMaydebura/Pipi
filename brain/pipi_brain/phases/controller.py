"""SessionController: runs the whole session (docs/INTERACTION_FLOW.md) and is the WozBackend.

How it works, in plain words:
- Each phase is a small handler (one module per phase) that returns the next phase.
  The controller runs the current handler as a task and logs every ``phase_change``.
- WoZ commands arrive in ``handle_woz`` (from the WoZ server, or typed ``/commands``).
  They are validated (``woz_commands.py``) and logged as ``woz_action``. Commands that change
  the flow become *directives* in a queue; the controller then stops the running phase at
  the next safe point (never in the middle of a sentence or a migration) and goes where the
  directive says. ``emergency_stop`` does not wait: it cancels everything at once.
- Jumping to a phase on the other body (e.g. ``goto_phase CHAT`` during FOCUS) runs the
  migration first, so the participant always sees Pipi move between bodies.
- A background watcher checks body health (WoZ state + alerts) and the break timer
  (``break_max_s`` -> a polite ROBOT_GOODBYE).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, get_args

from pipi_brain.bodies.base import Body
from pipi_brain.bodies.manager import BodyManager, ManagerSettings
from pipi_brain.config import AppConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.games.setup import GameSetup, check_session, load_game_setup
from pipi_brain.latency import summarize_turns
from pipi_brain.logging_study import StudyLogger
from pipi_brain.memory import Memory
from pipi_brain.phases import (
    chat,
    focus,
    games,
    goodbye,
    greeting,
    migration,
    persona_pick,
    robot_wake,
    setup,
)
from pipi_brain.phases.clock import Clock, RealClock, cancel_and_wait
from pipi_brain.phases.context import Next, PhaseContext
from pipi_brain.phases.events import SessionEvents
from pipi_brain.phases.flow import (
    BREAK_PHASES,
    GAME_PHASES,
    Directive,
    Trigger,
    side_of,
    successor,
)
from pipi_brain.phases.inputs import UserInputSource
from pipi_brain.phases.state import SessionState
from pipi_brain.phases.timers import Countdown, PauseState, SafePoints
from pipi_brain.phases.voice import Voice, VoiceSettings
from pipi_brain.phases.woz_signals import WozSignals
from pipi_brain.protocol import ActiveBody, Phase, StateUpdate, WozCommand
from pipi_brain.resilience import describe_error
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.bang import BangDetector
from pipi_brain.speech.base import Speaker, SpeechToText, TextToSpeech
from pipi_brain.speech.tts_cache import TtsCache
from pipi_brain.woz_api import CommandOutcome, WozListener

Handler = Callable[[PhaseContext], Awaitable[Next]]
ACTIVE_BODIES = frozenset(get_args(ActiveBody))


@dataclass(frozen=True)
class SessionDeps:
    """Everything external the session uses; tests pass fakes."""

    stt: SpeechToText
    tts: TextToSpeech
    speaker: Speaker
    dialogue: DialogueEngine
    input: UserInputSource
    bodies: Mapping[str, Body]
    gate: AudioGate
    clock: Clock = RealClock()
    tts_cache: TtsCache | None = None
    bang_detector: BangDetector | None = None  # quick-draw duel; None = typed / slow motion
    rng: random.Random | None = None  # games' randomness; tests pass a seeded one


@dataclass(frozen=True)
class _Outcome:
    phase: Phase
    trigger: Trigger
    command: str | None = None
    reason: str | None = None


class SessionController:
    def __init__(
        self,
        *,
        app: AppConfig,
        content: DialogueContent,
        logger: StudyLogger,
        deps: SessionDeps,
        participant_id: str,
        auto_start: bool,
        game_setup: GameSetup | None = None,
        reading_text: str | None = None,
        start_data: Mapping[str, Any] | None = None,
        emit: Callable[[str], None] = print,
    ) -> None:
        self.app = app
        self.content = content
        self.participant_id = participant_id
        # games.yaml + motions.yaml + the built games; a problem is a ConfigError right here
        self.games = game_setup or load_game_setup(app.games)
        check_session(self.games, app.session)
        self.registry = self.games.registry
        self.auto_start = auto_start
        self._deps = deps
        self._clock = deps.clock
        self._emit = emit
        self._start_data = dict(start_data or {})
        self._started = time.perf_counter()
        self.state = SessionState(
            memory=Memory(participant_id=participant_id, persona=app.persona.default)
        )
        self.events = SessionEvents(logger, phase=lambda: self.state.phase, body=self._active_name)
        self.pause = PauseState(self._clock)
        self.safe = SafePoints(
            retry_after_s=app.session.interrupt_retry_s, on_lost_cancel=self._on_lost_cancel
        )
        self.bodies = BodyManager(
            deps.bodies,
            robot_body=app.robot.body,
            settings=ManagerSettings(
                flight_s=app.session.flight_s,
                robot_connect_wait_s=app.session.robot_connect_wait_s,
                ack_timeout_s=app.bodies.ack_timeout_s,
                ack_retries=app.bodies.ack_retries,
                transition_animation=app.cues.transition_animation,
            ),
            clock=self._clock,
            log=lambda kind, data: self.events.log(kind, data),
            alert=self.events.alert,
        )
        self.voice = Voice(
            tts=deps.tts,
            cache=deps.tts_cache,
            speaker=deps.speaker,
            gate=deps.gate,
            bodies=self.bodies,
            events=self.events,
            safe=self.safe,
            pause=self.pause,
            clock=self._clock,
            settings=VoiceSettings(
                tts_timeout_s=app.timeouts.tts_s,
                playback_margin_s=app.timeouts.playback_margin_s,
                thinking_delay_s=app.session.thinking_delay_ms / 1000,
            ),
            on_spoken=lambda text: self.state.add_turn("pipi", text),
            on_latency=self._add_latency,
            emit=emit,
        )
        self.ctx = PhaseContext(
            app=app,
            content=content,
            state=self.state,
            events=self.events,
            voice=self.voice,
            bodies=self.bodies,
            stt=deps.stt,
            dialogue=deps.dialogue,
            input=deps.input,
            clock=self._clock,
            pause=self.pause,
            safe=self.safe,
            games=self.games,
            rng=deps.rng or random.Random(),
            woz_signals=WozSignals(),
            push_state=self.push_state,
            emit=emit,
            reading_text=reading_text,
            bang_detector=deps.bang_detector,
        )
        self._directives: asyncio.Queue[Directive] = asyncio.Queue()
        self._phase_task: asyncio.Task[Next] | None = None
        self._phase_started = self._clock.now()
        self._break_signalled: Countdown | None = None
        self._last_connected: dict[str, bool] = {}
        self.woz_tasks: set[asyncio.Task[Any]] = set()
        self._start_logged = False

    # --- WozBackend ----------------------------------------------------------------------------

    def snapshot(self) -> StateUpdate:
        state = self.state
        timer = state.phase_timer or state.break_timer
        active = self.bodies.active_name
        return StateUpdate(
            phase=state.phase,
            mode=self.app.mode,
            participant_id=self.participant_id,
            active_body=active if active in ACTIVE_BODIES else None,  # type: ignore[arg-type]
            timer=timer.info() if timer is not None else None,
            paused=self.pause.paused,
            memory_summary=self._memory_summary(),
            health=self.bodies.health(),
        )

    async def handle_woz(self, command: WozCommand) -> CommandOutcome:
        from pipi_brain.phases.woz_actions import apply_command

        try:
            outcome = await apply_command(self, command)
        except Exception as exc:  # the panel must always get an answer
            outcome = CommandOutcome(ok=False, error=f"internal error: {describe_error(exc)}")
            self.events.alert("error", f"WoZ command {command.command} failed: {outcome.error}")
        self.events.log(
            "woz_action",
            {
                "command": command.command,
                "args": dict(command.args),
                "reason": command.reason,
                "free_text": command.note,
                "command_id": command.id,
                "ok": outcome.ok,
                "error": outcome.error,
            },
        )
        return outcome

    def subscribe(self, listener: WozListener) -> Callable[[], None]:
        return self.events.subscribe(listener)

    # --- used by woz_actions -------------------------------------------------------------------

    def enqueue(self, directive: Directive) -> None:
        self._directives.put_nowait(directive)

    def push_state(self) -> None:
        self.events.push(self.snapshot())

    def spawn(self, work: Awaitable[Any]) -> None:
        """Background WoZ work (say, say_text); cancelled by emergency_stop."""
        task = asyncio.ensure_future(work)
        self.woz_tasks.add(task)
        task.add_done_callback(self.woz_tasks.discard)

    def _on_lost_cancel(self) -> None:
        """Safety net of the safe points: the phase ignored a stop request (see timers.py)."""
        self.events.alert(
            "warning",
            f"{self.state.phase} did not stop after a command; stopping it again. "
            "(This is a bug: please note the time and report it.)",
        )

    def emergency_stop(self) -> None:
        """Stop all motion and audio NOW (no safe point) and freeze until the WoZ decides."""
        self.state.halted = True
        self.pause.pause()
        self.enqueue(Directive("halt", command="emergency_stop"))
        if self._phase_task is not None:
            self._phase_task.cancel()
        for task in list(self.woz_tasks):
            task.cancel()
        self.voice.stop()
        self.bodies.stop_all()
        self.events.alert(
            "error", "EMERGENCY STOP: everything stopped. Resume, go to a phase or end."
        )
        self.push_state()

    # --- main loop -----------------------------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        """Run the session from SETUP to END; returns the summary (also on Ctrl+C: written)."""
        self.log_session_start()
        background = [asyncio.ensure_future(self._watch()), asyncio.ensure_future(self._prewarm())]
        reason = "interrupted"
        try:
            await self._loop()
            reason = "completed"
        finally:
            try:
                await cancel_and_wait([*background, *self.woz_tasks])
            finally:  # also when interrupted again while stopping: the log gets its summary
                summary = self._finalize(reason)
        return summary

    def log_session_start(self) -> None:
        """The first event of the log (called again by ``run``: written only once)."""
        if self._start_logged:
            return
        self._start_logged = True
        self.events.log("session_start", self._session_start_data())
        if self.bodies.robot is None:
            others = [n for n in self.bodies.names if n != "desktop_pet"]
            self.events.alert(
                "warning",
                f"No {self.bodies.robot_name} body in this session (robot.body in the config); "
                f"bodies: {', '.join(others) or 'none'}. Use switch_robot_body before the break.",
            )

    async def _loop(self) -> None:
        phase: Phase = "SETUP"
        self.push_state()
        while phase != "END":
            outcome = await self._run_phase(phase)
            target = self._route(outcome.phase)
            await self._prepare_bodies(target)
            self._enter(target, outcome)
            phase = target

    def _handler(self, phase: Phase) -> Handler:
        if phase == "SETUP":
            return lambda ctx: setup.run(ctx, auto_start=self.auto_start)
        handlers: dict[Phase, Handler] = {
            "PERSONA_PICK": persona_pick.run,
            "GREETING": greeting.run,
            "FOCUS": focus.run,
            "MIGRATE_OUT": migration.run_out,
            "ROBOT_WAKE": robot_wake.run,
            "CHAT": chat.run,
            "GAME_CROCODILE": games.run_crocodile,
            "GAME_MENU": games.run_menu,
            "GAME_CHOSEN": games.run_chosen,
            "ROBOT_GOODBYE": goodbye.run_goodbye,
            "MIGRATE_IN": migration.run_in,
            "RETURN": goodbye.run_return,
        }
        return handlers[phase]

    async def _run_phase(self, phase: Phase) -> _Outcome:
        task: asyncio.Task[Next] = asyncio.ensure_future(self._handler(phase)(self.ctx))
        self._phase_task = task
        try:
            while True:
                getter = asyncio.ensure_future(self._directives.get())
                waits: set[asyncio.Future[Any]] = {getter} if task.done() else {task, getter}
                try:
                    done, _ = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    if not getter.done():
                        await cancel_and_wait([getter])
                if getter in done:
                    outcome = await self._apply(getter.result(), phase, task)
                    if outcome is not None:
                        return outcome
                elif not task.cancelled():
                    return self._phase_result(phase, task)
        finally:
            self._phase_task = None
            await cancel_and_wait([task])

    async def _apply(
        self, directive: Directive, phase: Phase, task: asyncio.Task[Next]
    ) -> _Outcome | None:
        if directive.kind == "break_over" and (
            phase not in BREAK_PHASES or phase == "ROBOT_GOODBYE"
        ):
            return None  # the break already ended on its own
        if directive.kind == "end_game" and phase not in GAME_PHASES:
            return None
        if directive.kind == "halt":
            task.cancel()  # usually cancelled already by emergency_stop
            await asyncio.wait([task])
            return await self._wait_after_halt(phase)
        if not task.done():
            await self.safe.interrupt(task)
        return self._outcome(directive, phase)

    async def _wait_after_halt(self, phase: Phase) -> _Outcome:
        self._emit("  [EMERGENCY STOP] waiting for resume / goto / end ...")
        while True:
            directive = await self._directives.get()
            if directive.kind in ("halt", "break_over", "end_game"):
                continue
            self.state.halted = False
            return self._outcome(directive, phase)

    def _outcome(self, directive: Directive, phase: Phase) -> _Outcome:
        if directive.kind == "break_over":
            target: Phase = "ROBOT_GOODBYE"
        elif directive.kind == "restart":
            target = phase
        elif directive.kind in ("next", "end_game"):
            target = successor(phase, game_loop=self.app.session.game_loop) or "END"
        else:
            target = directive.target or "END"
        return _Outcome(target, directive.trigger, directive.command, directive.reason)

    def _phase_result(self, phase: Phase, task: asyncio.Task[Next]) -> _Outcome:
        error = task.exception()
        if error is None:
            result = task.result()
            return _Outcome(result.phase, result.trigger)
        # A bug in a phase must not end the session: report it and continue with the flow.
        self.events.log("phase_error", {"error": describe_error(error)})
        self.events.alert("error", f"{phase} failed ({describe_error(error)}); continuing.")
        nxt = successor(phase, game_loop=self.app.session.game_loop) or "END"
        return _Outcome(nxt, "error")

    def _route(self, target: Phase) -> Phase:
        """Insert a migration when the target phase lives on the other body."""
        side, active = side_of(target), self.bodies.active_side
        if side == "robot" and active != "robot" and not self.state.break_on_pet:
            self.state.after_migration = target
            return "MIGRATE_OUT"
        if side == "pet" and active == "robot":
            self.state.after_migration = target
            return "MIGRATE_IN"
        return target

    async def _prepare_bodies(self, target: Phase) -> None:
        if self.bodies.active is None and (side_of(target) == "pet" or target == "MIGRATE_OUT"):
            await self.bodies.appear_on_pet()

    def _enter(self, target: Phase, outcome: _Outcome) -> None:
        now = self._clock.now()
        previous = self.state.phase
        durations = self.state.phase_durations_s
        durations[previous] = durations.get(previous, 0.0) + (now - self._phase_started)
        self._phase_started = now
        data: dict[str, Any] = {"from": previous, "to": target, "trigger": outcome.trigger}
        if outcome.command is not None:
            data.update(command=outcome.command, reason=outcome.reason)
        if target != outcome.phase:
            data["via"] = target  # migration inserted before outcome.phase
            data["requested"] = outcome.phase
        self.events.log("phase_change", data)
        self.state.phase = target
        self.state.history = ()
        self.state.phase_timer = None
        self.state.focus_extra_s = 0.0
        if target not in BREAK_PHASES and target != "MIGRATE_OUT" and target != "MIGRATE_IN":
            self.state.break_timer = None
        self._emit(f"  [phase] {previous} -> {target} ({outcome.trigger})")
        self.push_state()

    # --- background ----------------------------------------------------------------------------

    async def _watch(self) -> None:
        self._last_connected = {name: h.connected for name, h in self.bodies.health().items()}
        while True:
            await self._clock.sleep(self.app.session.health_poll_s)
            self._check_health()
            self._check_break()

    def _check_health(self) -> None:
        changed = False
        for name, health in self.bodies.health().items():
            before = self._last_connected.get(name)
            if before is None or before == health.connected:
                self._last_connected[name] = health.connected
                continue
            self._last_connected[name] = health.connected
            changed = True
            relevant = name in (self.bodies.robot_name, "desktop_pet")
            if health.connected:
                self.events.alert("info", f"{name} connected again.")
            elif relevant:
                self.events.alert("warning", f"{name} disconnected.")
        if changed:
            self.push_state()

    def _check_break(self) -> None:
        timer = self.state.break_timer
        if timer is None or not timer.expired or self._break_signalled is timer:
            return
        if self.state.phase in BREAK_PHASES and self.state.phase != "ROBOT_GOODBYE":
            self._break_signalled = timer
            self.events.alert("info", "break_max_s reached: Pipi says goodbye now.")
            self.enqueue(Directive("break_over", trigger="timer", command="break_max"))

    async def _prewarm(self) -> None:
        cache = self._deps.tts_cache
        if cache is None:
            return
        texts = [
            text
            for variants in self.content.lines.values()
            for text in variants.values()
            if "{" not in text
        ]
        settings = self.app.tts_cache
        report = await cache.prewarm(
            texts, timeout_s=settings.prewarm_timeout_s, concurrency=settings.prewarm_concurrency
        )
        self.events.log("tts_prewarm", report.__dict__)
        if report.failed or report.timed_out:
            self.events.alert(
                "warning", f"TTS cache: {report.failed} fixed lines not ready (played live later)."
            )

    # --- helpers -------------------------------------------------------------------------------

    def _active_name(self) -> str | None:
        return self.bodies.active_name

    def _add_latency(self, latency: Any) -> None:
        self.state.latencies = (*self.state.latencies, latency)

    def _memory_summary(self) -> dict[str, str]:
        memory = self.state.memory
        summary = {"persona": memory.persona}
        if memory.name:
            summary["name"] = memory.name
        if memory.interests:
            summary["interests"] = ", ".join(i.label for i in memory.interests)
        if memory.reading_feeling:
            summary["reading_feeling"] = memory.reading_feeling
        if memory.word_help:
            summary["word_help"] = ", ".join(w.term for w in memory.word_help)
        if memory.game_events:
            summary["games"] = "; ".join(f"{e.game}: {e.summary}" for e in memory.game_events)
        return summary

    def _session_start_data(self) -> dict[str, Any]:
        app = self.app
        return {
            "mode": app.mode,
            "runner": "session",
            "input": self._deps.input.mode,
            "bodies": list(self.bodies.names),
            "robot_body": app.robot.body,
            "robot_side": app.pet.robot_side,
            "persona_default": app.persona.default,
            "persona_options": list(self.content.personas),
            "auto_start": self.auto_start,
            "game_loop": app.session.game_loop,
            "games": {
                "built": [game.id for game in self.registry.registered],
                "first_game": app.session.first_game,
                "default_game": app.session.default_game,
                "good_sport": self.games.config.good_sport,
                "bang_detector": self._deps.bang_detector is not None,
            },
            "cue_checklist": app.cues.model_dump(),
            **self._start_data,
        }

    def _finalize(self, reason: str) -> dict[str, Any]:
        now = self._clock.now()
        durations = dict(self.state.phase_durations_s)
        phase = self.state.phase
        durations[phase] = durations.get(phase, 0.0) + (now - self._phase_started)
        counts: dict[str, int] = {}
        for event in self.events.logger.read_events():
            counts[event["type"]] = counts.get(event["type"], 0) + 1
        summary: dict[str, Any] = {
            "session": self.events.logger.session_id,
            "end_reason": reason,
            "duration_ms": round((time.perf_counter() - self._started) * 1000),
            "final_phase": phase,
            "persona": self.state.persona,
            "input_mode": self._deps.input.mode,
            "user_turns": self.state.user_turns,
            "phase_durations_ms": {k: round(v * 1000) for k, v in durations.items()},
            "latency": summarize_turns(self.state.latencies),
            "event_counts": counts,
        }
        self.events.log(
            "session_end",
            {
                "reason": reason,
                "duration_ms": summary["duration_ms"],
                "phase_durations_ms": summary["phase_durations_ms"],
                "user_turns": summary["user_turns"],
                "latency": summary["latency"],
            },
        )
        logger = self.events.logger
        logger.write_json("memory.json", self.state.memory.model_dump(mode="json"))
        logger.write_json("summary.json", summary)
        self.push_state()
        return summary
