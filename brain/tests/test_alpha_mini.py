"""The real Alpha Mini body over RidK: moves file checks, the body, the connector.

Everything runs against a fake RidK session that records calls: these tests never reach the
real router. Only calls from the course examples may appear (``COURSE_EXAMPLE_URIS``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import SecretStr

from pipi_brain.bodies.alpha_mini import AlphaMiniBody, AlphaMiniSettings
from pipi_brain.bodies.alpha_mini_moves import MoveLibrary, load_moves
from pipi_brain.bodies.base import NOT_CONNECTED
from pipi_brain.bodies.ridk import RidkConnector
from pipi_brain.config import ConfigError, LoadedConfig
from pipi_brain.games.motions import load_motions
from pipi_brain.session_app import default_body_host, load_robot_moves
from pipi_brain.tools.robot_check import COURSE_EXAMPLE_URIS, NOD_FRAMES

from .conftest import CONFIG_DIR

REALM = "rie.0123456789abcdef"
SETTINGS = AlphaMiniSettings(call_timeout_s=1.0, stop_timeout_s=0.5, speech_s_per_char=0.0)


class FakeRidk:
    """Records every call; ``block`` makes calls to that URI hang until released."""

    def __init__(self, *, fail: str | None = None, block: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail
        self.block = block
        self.release = asyncio.Event()

    async def call(self, uri: str, **kwargs: Any) -> Any:
        assert uri in COURSE_EXAMPLE_URIS, f"{uri} is not a verified RidK call"
        self.calls.append((uri, kwargs))
        if uri == self.fail:
            raise RuntimeError("robot said no")
        if uri == self.block:
            await self.release.wait()
        return None

    def uris(self) -> list[str]:
        return [uri for uri, _ in self.calls]


class Log:
    def __init__(self) -> None:
        self.events: list[tuple[str, Mapping[str, Any]]] = []

    def __call__(self, event_type: str, data: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(data)))

    def types(self) -> list[str]:
        return [event for event, _ in self.events]


def moves() -> MoveLibrary:
    return load_moves(CONFIG_DIR / "alpha_mini.yaml")


def make_body(
    session: FakeRidk | None = None, settings: AlphaMiniSettings = SETTINGS
) -> tuple[AlphaMiniBody, Log]:
    log = Log()
    body = AlphaMiniBody(moves(), settings, log=log)
    if session is not None:
        body.attach(session)
    return body, log


async def settle(body: AlphaMiniBody) -> None:
    """Let a background move finish (frames steps wait in real time: keep them short)."""
    task = body._motion
    if task is not None:
        await asyncio.wait_for(task, 5)


# --- the moves file ----------------------------------------------------------------------------


def write_moves(tmp_path: Path, moves_: dict[str, Any], **verified: Any) -> Path:
    data = {
        "verified": {
            "joints": {"body.head.pitch": [-0.1, 0.1]},
            "behaviors": ["BlocklyStand"],
            **verified,
        },
        "moves": moves_,
    }
    path = tmp_path / "alpha_mini.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def frames(**joints: float) -> list[dict[str, Any]]:
    return [{"frames": [{"time": 300, "data": dict(joints)}]}]


def test_real_moves_file_uses_only_course_example_calls() -> None:
    library = moves()
    for name in library.names:
        for step in library.get(name) or ():
            uri, kwargs = step.call()
            assert uri in COURSE_EXAMPLE_URIS
            if step.behavior is not None:
                assert step.behavior in {"BlocklyStand", "BlocklyWaveRightArm"}
            for frame in kwargs.get("frames", []):
                assert set(frame["data"]) == {"body.head.pitch"}
                assert -0.1 <= frame["data"]["body.head.pitch"] <= 0.1
    # the nod is exactly the course example
    (nod,) = library.get("nod") or ()
    assert nod.call() == ("rom.actuator.motor.write", {"frames": list(NOD_FRAMES), "force": True})


@pytest.mark.parametrize(
    ("moves_", "problem"),
    [
        ({"x": frames(**{"body.arms.right.upper.pitch": 0.5})}, "is not verified"),
        ({"x": frames(**{"body.head.pitch": 0.4})}, "outside the verified range"),
        ({"x": [{"behavior": "BlocklyMoonwalk"}]}, "is not verified"),
    ],
)
def test_unverified_ridk_names_stop_the_brain(
    tmp_path: Path, moves_: dict[str, Any], problem: str
) -> None:
    with pytest.raises(ConfigError, match=problem):
        load_moves(write_moves(tmp_path, moves_))


@pytest.mark.parametrize(
    "step",
    [
        {},  # neither kind
        {"behavior": "BlocklyStand", "frames": [{"time": 1, "data": {"body.head.pitch": 0}}]},
        {"frames": [{"time": 500, "data": {"body.head.pitch": 0}}, {"time": 200, "data": {}}]},
    ],
)
def test_malformed_steps_are_rejected(tmp_path: Path, step: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        load_moves(write_moves(tmp_path, {"x": [step]}))


def test_motions_yaml_may_only_name_existing_moves(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    motions = load_motions(CONFIG_DIR / "motions.yaml")
    assert load_robot_moves(dev_config, motions).get("act_robot") is not None
    small = write_moves(tmp_path, {"idle": frames(**{"body.head.pitch": 0})})
    robot = dev_config.app.robot.model_copy(update={"moves_file": small})
    broken = replace(dev_config, app=dev_config.app.model_copy(update={"robot": robot}))
    with pytest.raises(ConfigError, match="act_robot"):
        load_robot_moves(broken, motions)


# --- the body ----------------------------------------------------------------------------------


async def test_not_connected_fails_softly() -> None:
    body, _ = make_body()
    assert not body.connected and body.health() == NOT_CONNECTED
    assert (await body.play_motion("nod")).error == NOT_CONNECTED
    spoken = await body.speak("Hi!", None)
    assert not spoken.delivered and not spoken.finished
    assert (await body.activate("wake_up")).error == NOT_CONNECTED
    assert not await body.wait_connected(0.01)


async def test_wait_connected_wakes_up_on_join() -> None:
    body, log = make_body()
    waiting = asyncio.ensure_future(body.wait_connected(2))
    await asyncio.sleep(0)
    body.attach(FakeRidk())
    assert await waiting and body.connected
    body.detach("router gone")
    assert not body.connected
    assert log.types() == ["body_connect", "body_disconnect"]


async def test_speak_uses_the_robots_voice_and_waits_the_least_speaking_time() -> None:
    session = FakeRidk()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    settings = AlphaMiniSettings(call_timeout_s=1.0, stop_timeout_s=0.5, speech_s_per_char=0.05)
    log = Log()
    body = AlphaMiniBody(moves(), settings, log=log, sleep=fake_sleep)
    body.attach(session)
    result = await body.speak("Watch closely!", None, "determined")  # 14 characters
    assert result.delivered and result.finished
    assert session.calls == [("rie.dialogue.say", {"text": "Watch closely!"})]
    assert len(slept) == 1 and 0.6 < slept[0] <= 0.7
    assert (await body.speak("   ", None)).finished  # the stop workaround: nothing is said
    assert len(session.calls) == 1


async def test_speak_failure_is_reported_not_raised() -> None:
    body, log = make_body(FakeRidk(fail="rie.dialogue.say"))
    result = await body.speak("Hello", None)
    assert not result.delivered and "robot said no" in (result.error or "")
    assert "body_error" in log.types()


async def test_play_motion_is_acked_at_once_and_plays_in_the_background() -> None:
    session = FakeRidk()
    body, _ = make_body(session)
    assert (await body.play_motion("celebrate")).ok
    await settle(body)
    assert session.calls == [("rom.optional.behavior.play", {"name": "BlocklyWaveRightArm"})]
    unknown = await body.play_motion("act_bird")  # no verified move for it
    assert not unknown.ok and "unknown motion" in (unknown.error or "")


async def test_a_new_motion_replaces_the_running_one() -> None:
    session = FakeRidk(block="rom.optional.behavior.play")
    body, _ = make_body(session)
    await body.play_motion("wave")
    await asyncio.sleep(0)
    running = body._motion
    session.block = None
    await body.play_motion("idle")
    await settle(body)
    assert running is not None and running.cancelled()
    assert session.uris() == ["rom.optional.behavior.play", "rom.actuator.motor.write"]


async def test_wake_up_and_sleep_are_awaited_moves() -> None:
    session = FakeRidk()
    body, _ = make_body(session)
    woke = await body.activate("wake_up")
    assert woke.ok
    assert session.calls[0] == ("rom.optional.behavior.play", {"name": "BlocklyStand"})
    assert session.uris() == ["rom.optional.behavior.play", "rom.actuator.motor.write"]
    slept = await body.deactivate("sleep")
    assert slept.ok and slept.elapsed_ms >= 1400  # waits for the last keyframe (1.5 s)


async def test_a_failing_step_stops_the_move() -> None:
    body, log = make_body(FakeRidk(fail="rom.optional.behavior.play"))
    result = await body.activate("wake_up")
    assert not result.ok and "step 1" in (result.error or "")
    assert "body_error" in log.types()


async def test_eyes_and_captions_are_accepted_and_logged_once() -> None:
    session = FakeRidk()
    body, log = make_body(session)
    assert (await body.set_eyes("happy")).ok and (await body.set_eyes("thinking")).ok
    assert (await body.show_caption("hi")).ok
    assert session.calls == []
    unsupported = [data["command"] for event, data in log.events if event == "body_unsupported"]
    assert unsupported == ["eyes", "caption"]


async def test_stop_cancels_the_move_and_stops_audio() -> None:
    session = FakeRidk(block="rom.optional.behavior.play")
    body, _ = make_body(session)
    await body.play_motion("wave")
    await asyncio.sleep(0)
    running = body._motion
    result = await body.stop()
    assert result.ok and running is not None and running.cancelled()
    assert session.uris()[-1] == "rom.actuator.audio.stop"


# --- the connector -----------------------------------------------------------------------------


class FakeComponent:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.stopped = False
        self.done: asyncio.Future[None] | None = None

    def on_join(self, fn: Any) -> None:
        self.handlers["join"] = fn

    def on_leave(self, fn: Any) -> None:
        self.handlers["leave"] = fn

    def start(self, loop: asyncio.AbstractEventLoop) -> asyncio.Future[None]:
        self.done = loop.create_future()
        return self.done

    def stop(self) -> None:
        self.stopped = True
        if self.done is not None and not self.done.done():
            self.done.set_result(None)


async def test_connector_attaches_each_joined_session_and_never_logs_the_realm() -> None:
    component = FakeComponent()
    seen: list[tuple[str, str]] = []
    body, log = make_body()

    def factory(url: str, realm: str) -> FakeComponent:
        seen.append((url, realm))
        return component

    connector = RidkConnector("ws://router", REALM, body, log=log, factory=factory)
    await connector.start()
    assert seen == [("ws://router", REALM)] and not body.connected
    session = FakeRidk()
    component.handlers["join"](session, None)
    assert body.connected
    component.handlers["leave"](session, type("Details", (), {"reason": f"bye {REALM}"})())
    assert not body.connected
    component.handlers["join"](session, None)  # autobahn reconnected
    assert body.connected
    await connector.stop()
    assert component.stopped and not body.connected
    assert REALM not in repr(log.events)


async def test_connection_failure_is_logged_without_the_realm() -> None:
    component = FakeComponent()
    body, log = make_body()
    connector = RidkConnector("ws://router", REALM, body, log=log, factory=lambda *_: component)
    await connector.start()
    assert component.done is not None
    component.done.set_exception(RuntimeError(f"no_such_realm {REALM}"))
    await asyncio.sleep(0)
    errors = [data["error"] for event, data in log.events if event == "body_error"]
    assert errors and "<realm>" in errors[0] and REALM not in repr(log.events)
    await connector.stop()


def test_the_session_adds_the_real_robot_only_with_a_realm(dev_config: LoadedConfig) -> None:
    def log(_event: str, _data: Mapping[str, Any]) -> None:
        return None

    without = default_body_host(dev_config, log, lambda _name: log)
    assert set(without.bodies) == {"desktop_pet", "fake_robot"}
    secrets = dev_config.secrets.model_copy(update={"ridk_realm": SecretStr(REALM)})
    host = default_body_host(replace(dev_config, secrets=secrets), log, lambda _name: log)
    assert set(host.bodies) == {"desktop_pet", "fake_robot", "alpha_mini"}
    assert not host.bodies["alpha_mini"].connected  # nothing connects before start()
