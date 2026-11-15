"""FakeRobotBody: the pet's protocol minus body_config; wake/sleep acked after the animation.

A fake link answers like the fake robot page would; no sockets here (see test_server.py).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pipi_brain.bodies.fake_robot import FakeRobotBody
from pipi_brain.protocol import Ack, Hello, SpeechDone

from .test_bodies import AUDIO, SETTINGS, EventLog

HELLO = Hello(body="fake_robot", version="0.1.0")


class FakeRobotPage:
    """Acks like web/src/fake-robot: activate/deactivate only after ``animation_s``."""

    def __init__(self, robot: FakeRobotBody, *, animation_s: float = 0.0) -> None:
        self.description = "fake-robot-page"
        self.robot = robot
        self.animation_s = animation_s
        self.sent: list[dict[str, Any]] = []

    async def send(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        delay = self.animation_s if message["type"] in {"activate", "deactivate"} else 0.0
        asyncio.get_running_loop().call_later(delay, self._answer, message)

    def _answer(self, message: dict[str, Any]) -> None:
        self.robot.receive(Ack(ref_id=message["id"], ok=True))
        if message["type"] == "speak":
            self.robot.receive(SpeechDone(ref_id=message["id"], duration_ms=100))

    async def close(self) -> None:
        pass


def connected_robot(**page_options: Any) -> tuple[FakeRobotBody, FakeRobotPage, EventLog]:
    log = EventLog()
    robot = FakeRobotBody(SETTINGS, log=log)
    page = FakeRobotPage(robot, **page_options)
    robot.attach(page, HELLO)
    return robot, page, log


async def test_connecting_sends_nothing_pet_specific() -> None:
    robot, page, log = connected_robot()
    await asyncio.sleep(0.01)
    assert robot.name == "fake_robot"
    assert robot.health() == "connected (fake robot 0.1.0)"
    assert page.sent == []
    assert log.of("body_connected") == [{"remote": "fake-robot-page", "version": "0.1.0"}]


async def test_wake_up_waits_for_the_animation_to_finish() -> None:
    robot, page, _ = connected_robot(animation_s=0.15)
    result = await robot.activate("wake_up")
    assert result.ok and result.elapsed_ms >= 140
    assert page.sent[-1] == {**page.sent[-1], "type": "activate", "entrance": "wake_up"}


async def test_sleep_longer_than_the_migration_timeout_is_a_timed_out_failure() -> None:
    robot, _, log = connected_robot(animation_s=SETTINGS.migration_timeout_s + 0.2)
    result = await robot.deactivate("sleep")
    assert not result.ok and result.timed_out
    assert log.of("body_error")[-1]["message_type"] == "deactivate"


async def test_speak_reports_speech_done() -> None:
    robot, page, _ = connected_robot()
    result = await robot.speak("Ta-da! Hi again!", AUDIO, "happy")
    assert result.delivered and result.finished and result.duration_ms == 100
    assert page.sent[-1]["audio_b64"]


async def test_not_connected_is_a_result_not_an_exception() -> None:
    robot = FakeRobotBody(SETTINGS, log=EventLog())
    assert robot.health() == "not connected"
    assert (await robot.activate("wake_up")).error == "not connected"
    assert not (await robot.speak("hi", None)).delivered
