"""Lab check for the real Alpha Mini through RidK (Robots in de Klas): is it there, how fast?

Run (from ``brain/``, with ``RIDK_REALM=rie...`` in ``../.env``):

    python -m pipi_brain.tools.robot_check --config ../config/dev.yaml --steps connect
    python -m pipi_brain.tools.robot_check --config ../config/dev.yaml  # say, stand, nod, wave
    python -m pipi_brain.tools.robot_check --config ../config/dev.yaml --steps touch,face
    python -m pipi_brain.tools.robot_check --config ../config/dev.yaml --steps audio \
        --audio-url URL

RidK is WAMP (autobahn, msgpack) through a router on the internet; the realm names one robot.
Every call used here comes from the course's example scripts (``COURSE_EXAMPLE_URIS``): nothing
is guessed. Each call has a timeout, its time is measured, and the results go to
``logs/ROBOTCHECK_<time>.json`` (never the realm) to fill in docs/ROBOT_RIDK.md §3-4.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pipi_brain.config import ConfigError, load_config
from pipi_brain.resilience import describe_error, elapsed_ms_since, timed_call, with_timeout

# Calls that appear in the course's example scripts (Nov 24 2026, RoboConneqt portal).
COURSE_EXAMPLE_URIS = frozenset(
    {
        "rie.dialogue.say",
        "rom.optional.behavior.play",
        "rom.actuator.motor.write",
        "rom.actuator.audio.stream",
        "rom.actuator.audio.stop",
        "rom.sensor.touch.stream",
        "rie.vision.face.find",
    }
)
TOUCH_TOPIC = "rom.sensor.touch.stream"
HEAD_TOUCH_KEYS = frozenset({"body.head.front", "body.head.middle", "body.head.rear"})
# The nod from the course example: head pitch over 2.4 s.
NOD_FRAMES = (
    {"time": 400, "data": {"body.head.pitch": 0.1}},
    {"time": 1200, "data": {"body.head.pitch": -0.1}},
    {"time": 2000, "data": {"body.head.pitch": 0.1}},
    {"time": 2400, "data": {"body.head.pitch": 0.0}},
)
DEFAULT_STEPS = ("say", "stand", "nod", "wave")
OPTIONAL_STEPS = ("touch", "face", "audio")
DEFAULT_SAY = "Hi! I'm Pipi. Can you hear me?"
TOUCH_WAIT_S = 15.0
DEFAULT_AUDIO_S = 8.0
VALUE_CHARS = 200
NOT_CONNECTED_HINT = (
    "Check: the robot is switched on and online (portal, Robots page: 'Last seen' is now), "
    "and RIDK_REALM is the realm from THAT robot's example code. "
    "'no_such_realm' in the lines above = the router does not know this realm right now."
)


class RidkSession(Protocol):
    async def call(self, uri: str, **kwargs: Any) -> Any: ...

    async def subscribe(self, handler: Callable[[Any], Any], topic: str) -> Any: ...

    def leave(self) -> Any: ...


@dataclass(frozen=True)
class CheckStep:
    name: str
    what: str
    uri: str
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    hold_s: float = 0.0  # wait this long after the call (e.g. let the audio play)


@dataclass(frozen=True)
class StepResult:
    name: str
    uri: str
    ok: bool
    elapsed_ms: int
    error: str | None = None
    timed_out: bool = False
    value: str | None = None  # what the robot answered (shortened), to learn the API


@dataclass(frozen=True)
class ConnectReport:
    connected: bool
    join_ms: int | None
    error: str | None
    work_result: Any = None


def build_steps(
    names: Sequence[str],
    *,
    say_text: str = DEFAULT_SAY,
    audio_url: str | None = None,
    audio_s: float = DEFAULT_AUDIO_S,
) -> list[CheckStep]:
    """The calls for each step name, exactly as in the course examples."""
    behavior = "rom.optional.behavior.play"
    simple: dict[str, CheckStep] = {
        "say": CheckStep("say", "built-in voice", "rie.dialogue.say", {"text": say_text}),
        "stand": CheckStep("stand", "stand up", behavior, {"name": "BlocklyStand"}),
        "nod": CheckStep(
            "nod",
            "head joint control (nod)",
            "rom.actuator.motor.write",
            {"frames": [dict(f) for f in NOD_FRAMES], "force": True},
        ),
        "wave": CheckStep(
            "wave", "wave (signature wave)", behavior, {"name": "BlocklyWaveRightArm"}
        ),
        "face": CheckStep("face", "look for a face (camera)", "rie.vision.face.find"),
        "touch": CheckStep("touch", "touch the head", TOUCH_TOPIC),
    }
    steps: list[CheckStep] = []
    for name in names:
        if name == "audio":
            if not audio_url:
                raise ValueError("the audio step needs --audio-url")
            steps.append(
                CheckStep(
                    "audio",
                    "play an audio URL",
                    "rom.actuator.audio.stream",
                    {"url": audio_url, "sync": False},
                    hold_s=audio_s,
                )
            )
            steps.append(CheckStep("audio_stop", "stop the audio", "rom.actuator.audio.stop"))
        elif name in simple:
            steps.append(simple[name])
        else:
            known = ", ".join([*DEFAULT_STEPS, *OPTIONAL_STEPS])
            raise ValueError(f"unknown step {name!r} (known: connect, {known})")
    return steps


async def run_steps(
    session: RidkSession,
    steps: Sequence[CheckStep],
    *,
    timeout_s: float,
    emit: Callable[[str], None] = print,
    touch_wait_s: float = TOUCH_WAIT_S,
) -> list[StepResult]:
    """Run every step in order; a failing step is recorded and the next one still runs."""
    results: list[StepResult] = []
    for step in steps:
        if step.name == "touch":
            emit(f"  touch: please touch the robot's head (waiting {touch_wait_s:g} s) ...")
            result = await wait_for_head_touch(session, timeout_s=touch_wait_s)
        else:
            result = await _call_step(session, step, timeout_s)
        results.append(result)
        emit(_describe(step, result))
        if step.hold_s and result.ok:
            await asyncio.sleep(step.hold_s)
    return results


async def _call_step(session: RidkSession, step: CheckStep, timeout_s: float) -> StepResult:
    outcome = await timed_call(lambda: session.call(step.uri, **step.kwargs), timeout_s)
    return StepResult(
        name=step.name,
        uri=step.uri,
        ok=outcome.ok,
        elapsed_ms=outcome.elapsed_ms,
        error=outcome.error,
        timed_out=outcome.timed_out,
        value=_short(outcome.value) if outcome.ok else None,
    )


async def wait_for_head_touch(session: RidkSession, *, timeout_s: float) -> StepResult:
    """Subscribe to the touch stream (as in the course example) and wait for a head touch."""
    start = time.perf_counter()
    touched: asyncio.Future[list[str]] = asyncio.get_running_loop().create_future()
    seen: set[str] = set()

    def on_frame(frame: Any) -> None:
        data = frame.get("data", {}) if isinstance(frame, Mapping) else {}
        seen.update(str(key) for key in data)
        pressed = sorted(key for key in HEAD_TOUCH_KEYS if data.get(key))
        if pressed and not touched.done():
            touched.set_result(pressed)

    # The stream call may only return when the stream ends (course example: it is the last
    # line of main), so it runs in the background while we listen for a head touch.
    stream: asyncio.Future[Any] | None = None
    try:
        await with_timeout(session.subscribe(on_frame, TOUCH_TOPIC), timeout_s)
        stream = asyncio.ensure_future(session.call(TOUCH_TOPIC))
        await asyncio.wait({touched, stream}, timeout=timeout_s, return_when="FIRST_EXCEPTION")
        if stream.done() and not stream.cancelled() and stream.exception() is not None:
            raise stream.exception()  # type: ignore[misc]  # the robot refused the stream
        pressed = await with_timeout(touched, max(0.0, timeout_s - (time.perf_counter() - start)))
    except TimeoutError:
        error = f"no head touch within {timeout_s:g} s (sensors seen: {sorted(seen) or 'none'})"
        return StepResult("touch", TOUCH_TOPIC, False, elapsed_ms_since(start), error, True)
    except Exception as exc:  # a lab tool: report and carry on
        return StepResult("touch", TOUCH_TOPIC, False, elapsed_ms_since(start), describe_error(exc))
    finally:
        if stream is not None and not stream.done():
            stream.cancel()
    return StepResult("touch", TOUCH_TOPIC, True, elapsed_ms_since(start), value=", ".join(pressed))


ComponentFactory = Callable[[str, str, Callable[[Any, Any], Awaitable[None]]], Any]


def autobahn_component(url: str, realm: str, main: Callable[[Any, Any], Awaitable[None]]) -> Any:
    """The real connection, set up like the course examples (msgpack, no retries)."""
    from autobahn.asyncio.component import Component  # only needed in the lab

    transport = {"url": url, "serializers": ["msgpack"], "max_retries": 0}
    return Component(transports=[transport], realm=realm, main=main)


async def connect_and_run(
    url: str,
    realm: str,
    work: Callable[[Any], Awaitable[Any]],
    *,
    connect_timeout_s: float,
    factory: ComponentFactory | None = None,
) -> ConnectReport:
    """Join the realm, run ``work(session)``, leave. Never raises; errors are in the report.

    ``factory`` defaults to the real autobahn component, looked up at call time (tests replace
    ``autobahn_component`` so they can never reach the real router)."""
    factory = factory if factory is not None else autobahn_component
    start = time.perf_counter()
    joined = asyncio.Event()
    box: dict[str, Any] = {}

    async def main(_loop: Any, session: Any) -> None:
        box["join_ms"] = elapsed_ms_since(start)
        joined.set()
        box["result"] = await work(session)

    component = factory(url, realm, main)
    running: asyncio.Future[Any] = asyncio.ensure_future(
        component.start(asyncio.get_running_loop())
    )
    join_wait = asyncio.ensure_future(joined.wait())
    try:
        await asyncio.wait(
            {running, join_wait}, timeout=connect_timeout_s, return_when=asyncio.FIRST_COMPLETED
        )
        if not joined.is_set():
            if not running.done():
                _stop(component)
                return ConnectReport(False, None, f"no connection within {connect_timeout_s:g} s")
            return ConnectReport(False, None, f"connection failed: {_failure(running)}")
        await running  # the work has its own timeouts per call
    except Exception as exc:  # a lab tool: report, never crash
        return ConnectReport(True, box.get("join_ms"), describe_error(exc), box.get("result"))
    finally:
        join_wait.cancel()
        if not running.done():
            running.cancel()
    return ConnectReport(True, box.get("join_ms"), None, box.get("result"))


def _stop(component: Any) -> None:
    try:
        component.stop()
    except Exception:  # already stopped or never started: nothing to do
        return


def _failure(future: asyncio.Future[Any]) -> str:
    if future.cancelled():
        return "cancelled"
    exc = future.exception()
    return describe_error(exc) if exc else "the connection ended before joining the realm"


def _short(value: Any) -> str | None:
    return None if value is None else repr(value)[:VALUE_CHARS]


def _describe(step: CheckStep, result: StepResult) -> str:
    status = "ok  " if result.ok else ("TIME" if result.timed_out else "FAIL")
    detail = result.error or (f"-> {result.value}" if result.value else "")
    return f"  [{status}] {step.name:<10} {result.elapsed_ms:>6} ms  {step.what}  {detail}".rstrip()


# --- command line ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="robot_check", description=__doc__.split("\n")[0])
    parser.add_argument("--config", type=Path, required=True, help="e.g. ../config/dev.yaml")
    parser.add_argument(
        "--steps",
        default=",".join(DEFAULT_STEPS),
        help=f"comma list: connect (only connect), {', '.join([*DEFAULT_STEPS, *OPTIONAL_STEPS])}",
    )
    parser.add_argument("--say", default=DEFAULT_SAY, help="text for the say step")
    parser.add_argument("--audio-url", default=None, help="audio the robot should play (audio)")
    parser.add_argument("--audio-seconds", type=float, default=DEFAULT_AUDIO_S)
    args = parser.parse_args(argv)
    try:
        loaded = load_config(args.config)
        names = [n.strip() for n in args.steps.split(",") if n.strip() and n.strip() != "connect"]
        steps = build_steps(
            names, say_text=args.say, audio_url=args.audio_url, audio_s=args.audio_seconds
        )
    except (ConfigError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    realm = loaded.secrets.ridk_realm
    if realm is None:
        print(
            "Error: no robot realm. Put RIDK_REALM=rie... (from the portal's example code) "
            f"into {loaded.app.env_file}",
            file=sys.stderr,
        )
        return 2
    robot = loaded.app.robot
    return asyncio.run(_check(robot.ridk_url, realm.get_secret_value(), steps, loaded))


async def _check(url: str, realm: str, steps: list[CheckStep], loaded: Any) -> int:
    robot = loaded.app.robot
    print(f"Connecting to {url} (realm from .env) ...")

    async def work(session: Any) -> list[StepResult]:
        print("  [ok  ] connected")
        return await run_steps(session, steps, timeout_s=robot.ridk_call_timeout_s)

    report = await connect_and_run(url, realm, work, connect_timeout_s=robot.ridk_connect_timeout_s)
    results: list[StepResult] = list(report.work_result or [])
    if report.join_ms is not None:
        print(f"  joined the realm in {report.join_ms} ms")
    if report.error:
        print(f"  [FAIL] {report.error}")
    path = _save_report(Path(loaded.app.logging.dir), url, report, results)
    print(f"Report: {path}")
    if not report.connected:
        print("Summary: NOT CONNECTED. " + NOT_CONNECTED_HINT)
        return 1
    if report.error is not None:
        print(f"Summary: CONNECTION LOST during the steps ({report.error}); results incomplete.")
        return 1
    failed = [r.name for r in results if not r.ok]
    print("Summary: " + (f"failed steps: {', '.join(failed)}" if failed else "all steps ok"))
    return 0


def _save_report(log_dir: Path, url: str, report: ConnectReport, results: list[StepResult]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"ROBOTCHECK_{stamp}.json"
    data = {
        "tool": "robot_check",
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "url": url,  # the realm is a secret and is never written
        "connected": report.connected,
        "join_ms": report.join_ms,
        "error": report.error,
        "steps": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(data, indent=2), "utf-8")
    return path


if __name__ == "__main__":
    sys.exit(main())
