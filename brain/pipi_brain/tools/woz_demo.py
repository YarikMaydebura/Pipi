"""Try the WoZ panel without a real session (dev tool).

Run: ``python -m pipi_brain.tools.woz_demo --config ../config/dev.yaml``

Starts the WoZ server with a simulated session (``DemoBackend``): phases advance on
commands, the timer counts down, fake turns with latencies and body-health changes appear.
Open the printed URL (after ``npm run build``) or ``cd web && npm run dev`` -> /woz/.
Nothing is spoken and no API is called. Commands are logged to ``logs/WOZDEMO_<time>/``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, get_args

from pipi_brain.config import ConfigError, load_config
from pipi_brain.logging_study import LoggerError, StudyLogger
from pipi_brain.protocol import (
    Alert,
    BodyHealth,
    BrainToWoz,
    Phase,
    StateUpdate,
    TimerInfo,
    Turn,
    TurnLatencies,
    WozCommand,
)
from pipi_brain.woz_api import CommandOutcome
from pipi_brain.woz_server import WozServerError, serve_woz

PHASES: tuple[Phase, ...] = get_args(Phase)
ROBOT_PHASES = frozenset(PHASES[PHASES.index("ROBOT_WAKE") : PHASES.index("MIGRATE_IN")])
TICK_S = 1.0
TURN_EVERY_TICKS = 6
DEMO_TURNS = itertools.cycle(
    [
        ("user", "I think I liked the part about octopuses.", 2100),
        ("pipi", "Octopuses have three hearts! Want to play a game?", 1700),
        ("user", "Uh, what was the word again?", 3400),  # slow on purpose (> 2.5 s budget)
        ("pipi", "Gills: how fish breathe under water.", 1300),
    ]
)


class DemoBackend:
    """A tiny simulated session implementing ``WozBackend`` (for manual panel checks)."""

    def __init__(self, mode: str, focus_s: int) -> None:
        self._listeners: list[Callable[[BrainToWoz], None]] = []
        self._focus_s = focus_s
        self.state = StateUpdate(
            phase="SETUP",
            mode=mode,  # type: ignore[arg-type]
            participant_id="DEMO",
            health={
                "desktop_pet": BodyHealth(connected=True),
                "fake_robot": BodyHealth(connected=True),
            },
        )

    def snapshot(self) -> StateUpdate:
        return self.state

    def subscribe(self, listener: Callable[[BrainToWoz], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _publish(self, message: BrainToWoz) -> None:
        for listener in list(self._listeners):
            listener(message)

    def _update(self, **changes: Any) -> None:
        self.state = self.state.model_copy(update=changes)
        self._publish(StateUpdate.model_validate(self.state.model_dump(exclude={"id", "ts"})))

    def _goto(self, phase: Phase) -> None:
        timer = TimerInfo(name="focus", remaining_s=self._focus_s, total_s=self._focus_s)
        body: str | None = "desktop_pet"
        if phase in ("SETUP", "END"):
            body = None
        elif phase in ROBOT_PHASES:
            body = "fake_robot"
        self._update(phase=phase, timer=timer if phase == "FOCUS" else None, active_body=body)

    async def handle_woz(self, command: WozCommand) -> CommandOutcome:
        name, args = command.command, command.args
        phase_index = PHASES.index(self.state.phase)
        if name == "start_session":
            if self.state.phase != "SETUP":
                return CommandOutcome(ok=False, error="session already started")
            self._goto("PERSONA_PICK")
        elif name == "next_phase":
            self._goto(PHASES[min(phase_index + 1, len(PHASES) - 1)])
        elif name == "goto_phase":
            target = args.get("phase")
            if target not in PHASES:
                return CommandOutcome(ok=False, error=f"unknown phase {target!r}")
            self._goto(target)  # type: ignore[arg-type]
        elif name == "extend_focus":
            return self._extend(args.get("seconds"))
        elif name in ("pause", "resume"):
            self._update(paused=name == "pause")
        elif name == "emergency_stop":
            self._update(paused=True)
            self._publish(Alert(level="warning", message="Emergency stop: all motion stopped"))
        elif name == "end_session":
            self._goto("END")
        elif name == "say_text":
            self._publish(Turn(speaker="pipi", text=str(args.get("text", ""))))
        elif name == "switch_robot_body":
            self._update(active_body="alpha_mini" if args.get("body") == "real" else "fake_robot")
        return CommandOutcome(ok=True)

    def _extend(self, seconds: object) -> CommandOutcome:
        timer = self.state.timer
        if timer is None:
            return CommandOutcome(ok=False, error="no focus timer running")
        if not isinstance(seconds, int) or seconds <= 0:
            return CommandOutcome(ok=False, error="seconds must be a positive integer")
        self._update(
            timer=TimerInfo(
                name=timer.name,
                remaining_s=timer.remaining_s + seconds,
                total_s=timer.total_s + seconds,
            )
        )
        return CommandOutcome(ok=True)

    async def run(self) -> None:
        """Count the timer down and produce fake turns / health blips."""
        for tick in itertools.count(1):
            await asyncio.sleep(TICK_S)
            timer = self.state.timer
            if timer is not None and not self.state.paused:
                remaining = max(0.0, timer.remaining_s - TICK_S)
                if remaining == 0:
                    self._goto("MIGRATE_OUT")
                elif tick % 5 == 0:  # the panel counts down locally between updates
                    self._update(timer=timer.model_copy(update={"remaining_s": remaining}))
                else:
                    self.state = self.state.model_copy(
                        update={"timer": timer.model_copy(update={"remaining_s": remaining})}
                    )
            if tick % TURN_EVERY_TICKS == 0 and self.state.phase not in ("SETUP", "END"):
                self._fake_turn()
            if tick % 40 == 0:
                self._toggle_robot_health()

    def _fake_turn(self) -> None:
        speaker, text, total = next(DEMO_TURNS)
        latencies = TurnLatencies(stt_ms=500, llm_ms=total - 900, tts_ms=400, total_ms=total)
        self._publish(Turn(speaker=speaker, text=text, latencies=latencies))  # type: ignore[arg-type]

    def _toggle_robot_health(self) -> None:
        robot = self.state.health.get("fake_robot", BodyHealth(connected=True))
        flipped = BodyHealth(
            connected=not robot.connected,
            last_error=None if not robot.connected else "connection lost (demo)",
        )
        self._update(health={**self.state.health, "fake_robot": flipped})
        if not flipped.connected:
            self._publish(Alert(level="error", message="Fake robot disconnected (demo)"))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="woz_demo", description=__doc__)
    parser.add_argument("--config", required=True, help="e.g. ../config/dev.yaml")
    return parser.parse_args(argv)


async def _run(config_path: str) -> None:
    loaded = load_config(config_path)
    logger = StudyLogger(loaded.app.logging.dir, "WOZDEMO")
    backend = DemoBackend(loaded.app.mode, loaded.app.timers.focus_s)

    def log(event_type: str, data: Mapping[str, Any]) -> None:
        logger.log(event_type, data, phase=backend.state.phase)

    print(f"Log: {logger.folder}")
    async with serve_woz(backend, loaded, log):
        print("Simulated session running. Ctrl+C to stop.")
        await backend.run()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(_run(args.config))
    except (ConfigError, LoggerError, WozServerError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
