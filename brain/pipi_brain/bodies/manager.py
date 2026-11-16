"""BodyManager: exactly one active body, and the migration choreography between them.

The manager works on a ``Mapping[str, Body]`` (the server exposes "desktop_pet" and
"fake_robot"; the real "alpha_mini" joins in M5 behind the same interface). It never knows
what a body is made of. Which body is the robot side comes from ``robot.body`` in the config
and can be swapped by the WoZ (``switch_robot_body``).

Migration (docs/INTERACTION_FLOW.md, identical for every participant):

    OUT: pet announces (+ signature_wave)  ->  pet deactivate(jump_out)  ->  ~0.8 s "flight"
         ->  robot activate(wake_up)                         [the greeting is ROBOT_WAKE]
    IN : robot deactivate(sleep)  ->  flight  ->  pet activate(jump_in) [recall = RETURN]

Every step has a timeout (inside the body), a fallback and a log entry. If the robot is
missing or does not wake up, Pipi stays on (or comes back to) the pet, the WoZ gets an alert,
and the caller says an explanation line. Nothing here raises.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pipi_brain.bodies.base import NOT_CONNECTED, Body, BodyResult, Entrance, Exit
from pipi_brain.bodies.channel import BodyChannel
from pipi_brain.phases.clock import Clock
from pipi_brain.protocol import BodyHealth, Calm, EyeState

PET = "desktop_pet"
ROBOT_BODIES: dict[str, str] = {"fake": "fake_robot", "real": "alpha_mini"}

Side = Literal["pet", "robot"]
Log = Callable[[str, Mapping[str, Any]], None]
Alert = Callable[[Literal["info", "warning", "error"], str], None]
Announce = Callable[[Body], Awaitable[None]]


@dataclass(frozen=True)
class ManagerSettings:
    flight_s: float  # silence between jump_out and wake_up
    robot_connect_wait_s: float  # how long a migration waits for a missing robot
    ack_timeout_s: float  # for the calm message
    ack_retries: int
    transition_animation: bool = True  # cue flag: False -> plain fade instead of jumps


@dataclass(frozen=True)
class MigrationStep:
    step: str
    body: str | None
    ok: bool
    error: str | None = None
    elapsed_ms: int = 0


@dataclass(frozen=True)
class MigrationResult:
    direction: Literal["out", "in"]
    success: bool
    steps: tuple[MigrationStep, ...]
    fallback: str | None = None  # e.g. "stay_on_pet"
    error: str | None = None


class BodyManager:
    def __init__(
        self,
        bodies: Mapping[str, Body],
        *,
        robot_body: str,
        settings: ManagerSettings,
        clock: Clock,
        log: Log,
        alert: Alert,
    ) -> None:
        self._bodies = dict(bodies)
        self._robot_name = robot_body
        self._settings = settings
        self._clock = clock
        self._log = log
        self._alert = alert
        self._active: str | None = None
        self._last_error: dict[str, str | None] = {}
        self._background: set[asyncio.Task[Any]] = set()

    # --- lookup ------------------------------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._bodies)

    def get(self, name: str) -> Body | None:
        return self._bodies.get(name)

    @property
    def pet(self) -> Body | None:
        return self._bodies.get(PET)

    @property
    def robot_name(self) -> str:
        return self._robot_name

    @property
    def robot(self) -> Body | None:
        return self._bodies.get(self._robot_name)

    @property
    def active_name(self) -> str | None:
        return self._active

    @property
    def active(self) -> Body | None:
        return self._bodies.get(self._active) if self._active else None

    @property
    def active_side(self) -> Side | None:
        if self._active is None:
            return None
        return "pet" if self._active == PET else "robot"

    def health(self) -> dict[str, BodyHealth]:
        return {
            name: BodyHealth(connected=body.connected, last_error=self._last_error.get(name))
            for name, body in self._bodies.items()
        }

    # --- simple commands ---------------------------------------------------------------------

    def _note(self, name: str, result: BodyResult) -> BodyResult:
        self._last_error[name] = None if result.ok else result.error
        return result

    async def set_eyes(self, state: EyeState, body: str | None = None) -> BodyResult:
        name = body or self._active
        target = self._bodies.get(name) if name else None
        if name is None or target is None or not target.connected:
            return BodyResult(ok=False, error=NOT_CONNECTED)
        return self._note(name, await target.set_eyes(state))

    async def play_motion(self, motion: str, body: str | None = None) -> BodyResult:
        name = body or self._active
        target = self._bodies.get(name) if name else None
        if name is None or target is None or not target.connected:
            return BodyResult(ok=False, error=NOT_CONNECTED)
        return self._note(name, await target.play_motion(motion))

    async def set_calm(self, on: bool) -> BodyResult:
        """Calm mode on the pet (FOCUS). Uses ``set_calm`` if the body has one, else its channel."""
        pet = self.pet
        if pet is None or not pet.connected:
            return BodyResult(ok=False, error=NOT_CONNECTED)
        setter = getattr(pet, "set_calm", None)
        channel = getattr(pet, "channel", None)
        if callable(setter):
            result: BodyResult = await setter(on)
        elif isinstance(channel, BodyChannel):
            result = await channel.request(
                Calm(on=on),
                timeout_s=self._settings.ack_timeout_s,
                retries=self._settings.ack_retries,
            )
        else:
            result = BodyResult(ok=False, error="body cannot switch calm mode")
        return self._note(PET, result)

    def stop_all(self) -> None:
        """Emergency stop: every connected body stops talking and moving, right now.

        Each body gets ``stop()`` (the protocol's ``stop`` message, short ack timeout). Only
        if a body does not confirm it, the old workaround is used: an empty ``speak`` (which
        interrupts the current speech on the pet), no caption and idle eyes.
        Runs in the background so the caller never waits.
        """
        for body in self._bodies.values():
            if body.connected:
                task = asyncio.ensure_future(self._stop_one(body))
                self._background.add(task)
                task.add_done_callback(self._background.discard)

    async def _stop_one(self, body: Body) -> None:
        result = self._note(body.name, await body.stop())
        if result.ok:
            return
        self._log(
            "body_fallback",
            {
                "body": body.name,
                "action": "stop",
                "error": result.error,
                "fallback": "empty_speak",
            },
        )
        await asyncio.gather(
            body.speak("", None, "idle"),
            body.show_caption(None),
            body.set_eyes("idle"),
            return_exceptions=True,
        )

    # --- entering the session ----------------------------------------------------------------

    async def appear_on_pet(self) -> BodyResult:
        """Pipi appears on the screen (PERSONA_PICK, or a WoZ jump into a pet phase)."""
        self._active = PET
        pet = self.pet
        if pet is None or not pet.connected:
            self._alert("warning", "Desktop pet not connected: Pipi talks through the laptop.")
            return BodyResult(ok=False, error=NOT_CONNECTED)
        entrance: Entrance = "jump_in" if self._settings.transition_animation else "fade_in"
        return self._note(PET, await pet.activate(entrance))

    async def robot_ready(self) -> str | None:
        """None if the robot side can take over, else the reason why not."""
        robot = self.robot
        if robot is None:
            return f"no {self._robot_name} body in this session"
        if not await robot.wait_connected(self._settings.robot_connect_wait_s):
            return f"{self._robot_name} not connected"
        return None

    # --- migration ---------------------------------------------------------------------------

    async def migrate_out(self, announce: Announce) -> MigrationResult:
        """Pet -> robot. ``announce`` speaks the signature line on the pet (with the wave)."""
        steps: list[MigrationStep] = []
        start = time.perf_counter()
        exit_anim: Exit = "jump_out" if self._settings.transition_animation else "fade_out"
        entrance: Entrance = "wake_up" if self._settings.transition_animation else "fade_in"
        self._log_migration("out", "start", to=self._robot_name, exit=exit_anim, entrance=entrance)
        problem = await self.robot_ready()
        if problem is not None:
            steps.append(MigrationStep("robot_check", self._robot_name, False, problem))
            return self._finish("out", start, steps, False, "stay_on_pet", problem)
        pet, robot = self.pet, self.robot
        assert robot is not None  # robot_ready checked it
        if pet is not None:
            await self._step(steps, "announce", PET, self._announce(announce, pet))
            await self._step(steps, "pet_exit", PET, pet.deactivate(exit_anim))
        await self._step(steps, "flight", None, self._flight())
        woke = await self._step(steps, "robot_wake", self._robot_name, robot.activate(entrance))
        if woke.ok:
            self._active = self._robot_name
            return self._finish("out", start, steps, True)
        # The robot did not wake up: Pipi jumps back onto the screen.
        if pet is not None:
            back: Entrance = "jump_in" if self._settings.transition_animation else "fade_in"
            await self._step(steps, "pet_back", PET, pet.activate(back))
        self._active = PET
        return self._finish("out", start, steps, False, "stay_on_pet", woke.error)

    async def migrate_in(self) -> MigrationResult:
        """Robot -> pet: the robot falls asleep, Pipi leaps back onto the screen."""
        steps: list[MigrationStep] = []
        start = time.perf_counter()
        exit_anim: Exit = "sleep" if self._settings.transition_animation else "fade_out"
        entrance: Entrance = "jump_in" if self._settings.transition_animation else "fade_in"
        self._log_migration("in", "start", to=PET, exit=exit_anim, entrance=entrance)
        robot = self.active if self.active_side == "robot" else None
        if robot is not None:
            await self._step(steps, "robot_sleep", robot.name, robot.deactivate(exit_anim))
            await self._step(steps, "flight", None, self._flight())
        self._active = PET
        pet = self.pet
        if pet is None:
            steps.append(MigrationStep("pet_enter", PET, False, "no desktop pet body"))
            return self._finish("in", start, steps, False, "laptop_speaker", "no desktop pet body")
        landed = await self._step(steps, "pet_enter", PET, pet.activate(entrance))
        if landed.ok:
            return self._finish("in", start, steps, True)
        return self._finish("in", start, steps, False, "laptop_speaker", landed.error)

    async def switch_robot_body(self, target: Literal["fake", "real"]) -> str | None:
        """Swap the robot-side body (demo backup). Returns an error text or None."""
        new_name = ROBOT_BODIES[target]
        new_body = self._bodies.get(new_name)
        if new_body is None:
            return f"no {new_name} body in this session"
        old_name = self._robot_name
        if new_name == old_name:
            return None
        self._robot_name = new_name
        self._log("cue_change", {"cue": "robot_body", "old": old_name, "new": new_name})
        if self._active != old_name:
            return None
        # The robot side is active right now: hand over between the two robot bodies.
        steps: list[MigrationStep] = []
        start = time.perf_counter()
        old_body = self._bodies.get(old_name)
        if old_body is not None and old_body.connected:
            await self._step(steps, "old_robot_sleep", old_name, old_body.deactivate("sleep"))
        woke = await self._step(steps, "new_robot_wake", new_name, new_body.activate("wake_up"))
        self._active = new_name
        self._log(
            "migration",
            {
                "direction": "robot_switch",
                "stage": "end",
                "from": old_name,
                "to": new_name,
                "success": woke.ok,
                "steps": [step.__dict__ for step in steps],
                "duration_ms": _ms(start),
            },
        )
        return None if woke.ok else f"{new_name} did not wake up: {woke.error}"

    # --- helpers -----------------------------------------------------------------------------

    async def _announce(self, announce: Announce, pet: Body) -> BodyResult:
        await announce(pet)
        return BodyResult(ok=True)

    async def _flight(self) -> BodyResult:
        await self._clock.sleep(self._settings.flight_s)
        return BodyResult(ok=True)

    async def _step(
        self,
        steps: list[MigrationStep],
        step: str,
        body: str | None,
        action: Awaitable[BodyResult],
    ) -> BodyResult:
        start = time.perf_counter()
        result = await action
        if body is not None:
            self._note(body, result)
        steps.append(MigrationStep(step, body, result.ok, result.error, _ms(start)))
        return result

    def _log_migration(self, direction: str, stage: str, **data: Any) -> None:
        source = PET if direction == "out" else self._active
        self._log("migration", {"direction": direction, "stage": stage, "from": source, **data})

    def _finish(
        self,
        direction: Literal["out", "in"],
        start: float,
        steps: list[MigrationStep],
        success: bool,
        fallback: str | None = None,
        error: str | None = None,
    ) -> MigrationResult:
        result = MigrationResult(direction, success, tuple(steps), fallback, error)
        self._log(
            "migration",
            {
                "direction": direction,
                "stage": "end",
                "success": success,
                "active": self._active,
                "fallback": fallback,
                "error": error,
                "steps": [step.__dict__ for step in steps],
                "duration_ms": _ms(start),
            },
        )
        if not success:
            where = "the pet" if self._active == PET else str(self._active)
            self._alert("error", f"Migration {direction} failed ({error}); Pipi is on {where}.")
        return result


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
