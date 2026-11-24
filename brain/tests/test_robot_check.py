"""The lab check for the Alpha Mini (RidK over WAMP): fake sessions, no network, no robot."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from pipi_brain.tools import robot_check
from pipi_brain.tools.robot_check import (
    COURSE_EXAMPLE_URIS,
    HEAD_TOUCH_KEYS,
    build_steps,
    connect_and_run,
    run_steps,
    wait_for_head_touch,
)

REALM = "rie.secret0123456789"
QUICK_S = 0.05


@pytest.fixture(autouse=True)
def no_real_robot(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may ever reach the real RidK router (a test replaces this when it needs one)."""

    def refuse(*_args: Any) -> Any:
        raise AssertionError("a test tried to connect to the real RidK router")

    monkeypatch.setattr(robot_check, "autobahn_component", refuse)


class FakeSession:
    """Answers RidK calls like the robot; can fail or hang on chosen URIs."""

    def __init__(
        self, *, fail: Mapping[str, str] | None = None, hang: set[str] | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = dict(fail or {})
        self.hang = set(hang or set())
        self.handlers: dict[str, Callable[[Any], Any]] = {}
        self.left = False

    async def call(self, uri: str, **kwargs: Any) -> Any:
        self.calls.append((uri, kwargs))
        if uri in self.hang:
            await asyncio.sleep(10)
        if uri in self.fail:
            raise RuntimeError(self.fail[uri])
        return None

    async def subscribe(self, handler: Callable[[Any], Any], topic: str) -> None:
        self.handlers[topic] = handler

    def leave(self) -> None:
        self.left = True

    def uris(self) -> list[str]:
        return [uri for uri, _ in self.calls]


class FakeComponent:
    """Stands in for autobahn's Component: start() joins, then runs main(loop, session)."""

    def __init__(self, session: FakeSession, *, refuse: str | None = None, hang: bool = False):
        self.session = session
        self.refuse = refuse
        self.hang = hang
        self.main: Callable[[Any, Any], Awaitable[None]] | None = None
        self.stopped = False

    def factory(self, url: str, realm: str, main: Callable[[Any, Any], Awaitable[None]]) -> Any:
        assert url.startswith("ws") and realm == REALM
        self.main = main
        return self

    def start(self, loop: Any = None) -> asyncio.Future[None]:
        return asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        if self.hang:
            await asyncio.sleep(10)
        if self.refuse:
            raise ConnectionError(self.refuse)
        assert self.main is not None
        await self.main(asyncio.get_running_loop(), self.session)

    def stop(self) -> None:
        self.stopped = True


# --- the steps --------------------------------------------------------------------------------


def test_every_step_uses_only_calls_from_the_course_examples() -> None:
    # CLAUDE.md: never guess RidK function names.
    steps = build_steps(
        ["say", "stand", "nod", "wave", "face", "audio"], audio_url="https://example.org/a.mp3"
    )
    assert {step.uri for step in steps} <= COURSE_EXAMPLE_URIS
    assert [step.name for step in steps][:4] == ["say", "stand", "nod", "wave"]


def test_the_default_check_says_hello_stands_nods_and_waves() -> None:
    steps = build_steps(robot_check.DEFAULT_STEPS)
    assert [step.uri for step in steps] == [
        "rie.dialogue.say",
        "rom.optional.behavior.play",
        "rom.actuator.motor.write",
        "rom.optional.behavior.play",
    ]
    nod = steps[2]
    assert nod.kwargs["force"] is True and len(nod.kwargs["frames"]) == 4


def test_audio_needs_a_url_and_ends_with_a_stop() -> None:
    with pytest.raises(ValueError, match="audio"):
        build_steps(["audio"])
    steps = build_steps(["audio"], audio_url="http://laptop:8766/x.wav", audio_s=3)
    assert [s.uri for s in steps] == ["rom.actuator.audio.stream", "rom.actuator.audio.stop"]
    assert steps[0].kwargs == {"url": "http://laptop:8766/x.wav", "sync": False}
    assert steps[0].hold_s == 3


def test_unknown_step_names_are_refused() -> None:
    with pytest.raises(ValueError, match="dance"):
        build_steps(["dance"])


# --- running them -------------------------------------------------------------------------------


async def test_run_steps_records_success_failure_and_timeout_and_never_stops_early() -> None:
    session = FakeSession(fail={"rie.dialogue.say": "no tts"}, hang={"rom.actuator.motor.write"})
    lines: list[str] = []

    results = await run_steps(
        session, build_steps(robot_check.DEFAULT_STEPS), timeout_s=QUICK_S, emit=lines.append
    )

    assert [(r.name, r.ok) for r in results] == [
        ("say", False),
        ("stand", True),
        ("nod", False),
        ("wave", True),
    ]
    assert "no tts" in (results[0].error or "")
    assert results[2].timed_out
    assert len(lines) == 4 and all(r.elapsed_ms >= 0 for r in results)


async def test_head_touch_is_reported_with_the_sensor_names() -> None:
    session = FakeSession()
    waiting = asyncio.ensure_future(wait_for_head_touch(session, timeout_s=1))
    for _ in range(5):
        await asyncio.sleep(0)
    handler = session.handlers["rom.sensor.touch.stream"]

    handler({"data": {"body.head.front": False}})
    handler({"data": {"body.head.middle": True, "body.hand.left": False}})
    result = await waiting

    assert result.ok and result.value == "body.head.middle"
    assert "body.head.middle" in HEAD_TOUCH_KEYS
    assert session.uris() == ["rom.sensor.touch.stream"]


async def test_a_touch_counts_even_while_the_stream_call_has_not_returned() -> None:
    # In the course example the stream call is the last thing main() does: it may only
    # return when the stream ends. Touches must be heard while it is still running.
    session = FakeSession(hang={"rom.sensor.touch.stream"})
    waiting = asyncio.ensure_future(wait_for_head_touch(session, timeout_s=1))
    for _ in range(5):
        await asyncio.sleep(0)

    session.handlers["rom.sensor.touch.stream"]({"data": {"body.head.front": True}})
    result = await waiting

    assert result.ok and result.value == "body.head.front"


async def test_no_head_touch_is_a_timeout_not_a_crash() -> None:
    result = await wait_for_head_touch(FakeSession(), timeout_s=QUICK_S)
    assert not result.ok and result.timed_out


# --- connecting -------------------------------------------------------------------------------


async def test_connect_and_run_reports_the_join_time_and_the_work() -> None:
    session = FakeSession()
    component = FakeComponent(session)

    async def work(s: Any) -> str:
        await s.call("rie.dialogue.say", text="hi")
        return "done"

    report = await connect_and_run(
        "ws://robot", REALM, work, connect_timeout_s=1, factory=component.factory
    )

    assert report.connected and report.error is None and report.work_result == "done"
    assert report.join_ms is not None and report.join_ms >= 0
    assert session.uris() == ["rie.dialogue.say"]


async def test_a_refused_connection_is_a_readable_error() -> None:
    component = FakeComponent(FakeSession(), refuse="realm not found")

    report = await connect_and_run(
        "ws://robot", REALM, _nothing, connect_timeout_s=1, factory=component.factory
    )

    assert not report.connected and "realm not found" in (report.error or "")


async def test_no_answer_from_the_server_times_out_and_stops_the_component() -> None:
    component = FakeComponent(FakeSession(), hang=True)

    report = await connect_and_run(
        "ws://robot", REALM, _nothing, connect_timeout_s=QUICK_S, factory=component.factory
    )

    assert not report.connected and "no connection" in (report.error or "")
    assert component.stopped


async def _nothing(session: Any) -> None:
    return None


# --- the command line ---------------------------------------------------------------------------


@pytest.fixture
def lab_config(tmp_config_dir: Path, no_env_secrets: None, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A dev config whose logs go to a temp folder; the realm is a fake one."""
    monkeypatch.setenv("RIDK_REALM", REALM)
    config = tmp_config_dir / "dev.yaml"
    config.write_text("extends: base.yaml\nmode: dev\nlogging:\n  dir: lab_logs\n", "utf-8")
    return config


def _reports(config: Path) -> list[Path]:
    return list((config.parent / "lab_logs").glob("ROBOTCHECK_*.json"))


def test_main_without_a_realm_explains_what_to_do(
    lab_config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("RIDK_REALM")  # and the temp .env has none either

    assert robot_check.main(["--config", str(lab_config)]) == 2
    assert "RIDK_REALM" in capsys.readouterr().err


def test_main_runs_the_check_writes_a_report_and_never_shows_the_realm(
    lab_config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    session = FakeSession()
    component = FakeComponent(session)
    monkeypatch.setattr(robot_check, "autobahn_component", component.factory)

    code = robot_check.main(["--config", str(lab_config), "--steps", "say,wave"])

    out = capsys.readouterr()
    assert code == 0
    assert session.uris() == ["rie.dialogue.say", "rom.optional.behavior.play"]
    reports = _reports(lab_config)
    assert len(reports) == 1
    saved = json.loads(reports[0].read_text("utf-8"))
    assert saved["connected"] is True and [s["name"] for s in saved["steps"]] == ["say", "wave"]
    everything = out.out + out.err + reports[0].read_text("utf-8")
    assert REALM not in everything and "rie.secret" not in everything


def test_main_connect_only_moves_nothing(lab_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    monkeypatch.setattr(robot_check, "autobahn_component", FakeComponent(session).factory)

    assert robot_check.main(["--config", str(lab_config), "--steps", "connect"]) == 0
    assert session.calls == []
    assert len(_reports(lab_config)) == 1


def test_a_connection_lost_during_the_steps_is_not_reported_as_ok(
    lab_config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Lab, Nov 24: the router dropped the connection while a call hung; the summary said ok.
    component = FakeComponent(FakeSession())
    original = component.factory

    def factory(url: str, realm: str, main: Any) -> Any:
        original(url, realm, main)
        component.main = lambda loop, session: _join_then_drop(main, loop, session)
        return component

    monkeypatch.setattr(robot_check, "autobahn_component", factory)

    assert robot_check.main(["--config", str(lab_config), "--steps", "say"]) == 1
    out = capsys.readouterr().out
    assert "all steps ok" not in out and "CONNECTION LOST" in out


async def _join_then_drop(main: Any, loop: Any, session: Any) -> None:
    """Join (main starts), then the connection dies before the work can finish."""
    task = asyncio.ensure_future(main(loop, session))
    await asyncio.sleep(0)
    task.cancel()
    raise ConnectionError("Component failed: Exhausted all transport connect attempts")


def test_main_returns_1_when_the_robot_cannot_be_reached(
    lab_config: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    component = FakeComponent(FakeSession(), refuse="no such realm")
    monkeypatch.setattr(robot_check, "autobahn_component", component.factory)

    assert robot_check.main(["--config", str(lab_config), "--steps", "say"]) == 1

    out = capsys.readouterr().out
    assert "NOT CONNECTED" in out and "failed: []" not in out
    assert "switched on" in out  # what to check next
