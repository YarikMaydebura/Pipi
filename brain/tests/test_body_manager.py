"""BodyManager: active body, migration choreography and its fallbacks, calm mode, stop."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from pipi_brain.bodies.base import Body, BodyResult, Entrance
from pipi_brain.bodies.desktop_pet import DesktopPetBody
from pipi_brain.bodies.manager import BodyManager, ManagerSettings
from pipi_brain.fakes import FakeBody, FakeClock

from .test_bodies import HELLO, SETTINGS, EventLog, FakePetLink


class Alerts:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def __call__(self, level: Any, message: str) -> None:
        self.items.append((level, message))


def manager(
    bodies: Mapping[str, Body],
    *,
    robot: str = "fake_robot",
    animations: bool = True,
    clock: FakeClock | None = None,
) -> tuple[BodyManager, EventLog, Alerts]:
    log, alerts = EventLog(), Alerts()
    settings = ManagerSettings(
        flight_s=0.8,
        robot_connect_wait_s=0,
        ack_timeout_s=0.1,
        ack_retries=1,
        transition_animation=animations,
    )
    mgr = BodyManager(
        bodies,
        robot_body=robot,
        settings=settings,
        clock=clock or FakeClock(),
        log=log,
        alert=alerts,
    )
    return mgr, log, alerts


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def body(self, name: str, **kw: Any) -> FakeBody:
        recorder = self

        class Recording(FakeBody):
            def _result(self, call: str, arg: object) -> BodyResult:
                recorder.calls.append((f"{name}.{call}", arg))
                return super()._result(call, arg)

        return Recording(name=name, **kw)


async def run_with_clock(clock: FakeClock, coro: Any) -> Any:
    jumper = asyncio.ensure_future(clock.autojump())
    try:
        return await asyncio.wait_for(coro, 5)
    finally:
        jumper.cancel()


async def test_migrate_out_and_in_follow_the_choreography() -> None:
    rec, clock = Recorder(), FakeClock()
    pet, robot = rec.body("desktop_pet"), rec.body("fake_robot")
    mgr, log, alerts = manager({"desktop_pet": pet, "fake_robot": robot}, clock=clock)
    await mgr.appear_on_pet()
    announced: list[str] = []

    async def announce(body: Body) -> None:
        announced.append(body.name)
        rec.calls.append(("announce", body.name))

    start = clock.now()
    result = await run_with_clock(clock, mgr.migrate_out(announce))
    assert result.success and mgr.active_name == "fake_robot" and mgr.active_side == "robot"
    assert clock.now() - start == pytest.approx(0.8)  # the flight
    back = await run_with_clock(clock, mgr.migrate_in())
    assert back.success and mgr.active_name == "desktop_pet"
    assert rec.calls == [
        ("desktop_pet.activate", "jump_in"),
        ("announce", "desktop_pet"),
        ("desktop_pet.deactivate", "jump_out"),
        ("fake_robot.activate", "wake_up"),
        ("fake_robot.deactivate", "sleep"),
        ("desktop_pet.activate", "jump_in"),
    ]
    stages = [(d["direction"], d["stage"]) for d in log.of("migration")]
    assert stages == [("out", "start"), ("out", "end"), ("in", "start"), ("in", "end")]
    assert alerts.items == []


async def test_missing_robot_means_no_announcement_and_an_alert() -> None:
    pet = FakeBody(name="desktop_pet")
    mgr, log, alerts = manager({"desktop_pet": pet})
    await mgr.appear_on_pet()
    called: list[str] = []

    async def announce(body: Body) -> None:
        called.append(body.name)

    result = await mgr.migrate_out(announce)
    assert not result.success and result.fallback == "stay_on_pet"
    assert "no fake_robot body" in (result.error or "")
    assert called == [] and mgr.active_name == "desktop_pet"
    assert alerts.items and alerts.items[0][0] == "error"
    assert log.of("migration")[-1]["steps"][0]["step"] == "robot_check"


async def test_disconnected_robot_is_not_ready() -> None:
    mgr, _, _ = manager(
        {"desktop_pet": FakeBody(name="desktop_pet"), "fake_robot": FakeBody(connected=False)}
    )
    assert await mgr.robot_ready() == "fake_robot not connected"


async def test_robot_that_fails_to_wake_sends_pipi_back() -> None:
    class NoWake(FakeBody):
        async def activate(self, entrance: Entrance) -> BodyResult:
            return BodyResult(ok=False, error="no ack")

    pet = FakeBody(name="desktop_pet")
    mgr, _, alerts = manager({"desktop_pet": pet, "fake_robot": NoWake(name="fake_robot")})
    await mgr.appear_on_pet()

    async def announce(body: Body) -> None:
        return None

    clock = mgr._clock  # type: ignore[attr-defined]
    result = await run_with_clock(clock, mgr.migrate_out(announce))
    assert not result.success and mgr.active_name == "desktop_pet"
    assert pet.calls[-1] == ("activate", "jump_in")
    assert mgr.health()["fake_robot"].last_error == "no ack"
    assert alerts.items[-1][0] == "error"


async def test_without_transition_animation_bodies_fade() -> None:
    rec, clock = Recorder(), FakeClock()
    pet, robot = rec.body("desktop_pet"), rec.body("fake_robot")
    mgr, _, _ = manager({"desktop_pet": pet, "fake_robot": robot}, animations=False, clock=clock)

    async def announce(body: Body) -> None:
        return None

    await run_with_clock(clock, mgr.migrate_out(announce))
    await run_with_clock(clock, mgr.migrate_in())
    assert ("desktop_pet.deactivate", "fade_out") in rec.calls
    assert ("fake_robot.activate", "fade_in") in rec.calls
    assert ("fake_robot.deactivate", "fade_out") in rec.calls


async def test_switch_robot_body_when_not_active_only_changes_the_name() -> None:
    mgr, log, _ = manager(
        {"desktop_pet": FakeBody(), "fake_robot": FakeBody(), "alpha_mini": FakeBody()}
    )
    assert await mgr.switch_robot_body("real") is None
    assert mgr.robot_name == "alpha_mini"
    assert log.of("cue_change") == [{"cue": "robot_body", "old": "fake_robot", "new": "alpha_mini"}]
    assert "no" in (await manager({"desktop_pet": FakeBody()})[0].switch_robot_body("real") or "")


async def test_calm_uses_the_body_channel_for_websocket_bodies() -> None:
    pet = DesktopPetBody(SETTINGS, robot_side="right", log=EventLog())
    link = FakePetLink(pet)
    pet.attach(link, HELLO)
    mgr, _, _ = manager({"desktop_pet": pet})
    assert (await mgr.set_calm(True)).ok
    assert (await mgr.set_calm(False)).ok
    calm = [m for m in link.sent if m["type"] == "calm"]
    assert [m["on"] for m in calm] == [True, False]


async def test_calm_with_fake_body_and_missing_pet() -> None:
    pet = FakeBody(name="desktop_pet")
    mgr, _, _ = manager({"desktop_pet": pet})
    assert (await mgr.set_calm(True)).ok and pet.calls == [("calm", True)]
    no_pet, _, _ = manager({"fake_robot": FakeBody(name="fake_robot")})
    assert not (await no_pet.set_calm(True)).ok


async def test_stop_all_interrupts_every_connected_body() -> None:
    pet, robot = FakeBody(name="desktop_pet"), FakeBody(name="fake_robot", connected=False)
    mgr, _, _ = manager({"desktop_pet": pet, "fake_robot": robot})
    mgr.stop_all()
    for _ in range(5):
        await asyncio.sleep(0)
    assert pet.calls == [("stop", None)]  # the protocol's stop message, nothing else needed
    assert robot.calls == []


async def test_stop_all_falls_back_to_the_workaround_when_stop_is_not_acked() -> None:
    pet = FakeBody(name="desktop_pet", stop_ok=False)
    mgr, log, _ = manager({"desktop_pet": pet})
    mgr.stop_all()
    for _ in range(5):
        await asyncio.sleep(0)
    assert pet.calls[0] == ("stop", None)
    assert ("speak", "") in pet.calls and ("caption", None) in pet.calls
    assert ("eyes", "idle") in pet.calls
    fallback = log.of("body_fallback")[0]
    assert fallback["action"] == "stop" and fallback["fallback"] == "empty_speak"
    assert mgr.health()["desktop_pet"].last_error == "no ack within 1 s"


async def test_commands_on_missing_bodies_fail_softly() -> None:
    mgr, _, _ = manager({"desktop_pet": FakeBody(name="desktop_pet")})
    assert not (await mgr.set_eyes("happy")).ok  # nothing active yet
    assert not (await mgr.play_motion("wave", body="nope")).ok
    await mgr.appear_on_pet()
    assert (await mgr.set_eyes("happy")).ok
    assert set(mgr.health()) == {"desktop_pet"}
