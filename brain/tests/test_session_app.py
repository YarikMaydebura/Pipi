"""``--session``: wiring of body server, controller, terminal commands and the WoZ hook."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pipi_brain import session_app
from pipi_brain.__main__ import EXIT_MISSING_KEY, EXIT_OK, main
from pipi_brain.bodies.base import Body
from pipi_brain.config import ConfigError, LoadedConfig, load_config
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.fakes import (
    FakeBlinkDetector,
    FakeBody,
    FakeChatModel,
    FakeClock,
    FakeSpeaker,
    FakeSpeechToText,
    FakeTextInput,
    FakeTextToSpeech,
)
from pipi_brain.games.config import GamesConfig
from pipi_brain.games.setup import load_game_setup
from pipi_brain.session_app import SessionAppOptions, run_session
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.vision.base import BlinkDetector
from pipi_brain.voice_app import SessionOptions
from pipi_brain.voice_loop import VoiceLoopDeps
from pipi_brain.woz_api import WozBackend

from .conftest import CONFIG_DIR, FAKE_API_KEY
from .session_harness import app_with


def fake_deps(lines: list[str | None]) -> Any:
    async def factory(
        loaded: LoadedConfig, options: SessionOptions, gate: AudioGate
    ) -> tuple[VoiceLoopDeps, dict[str, str]]:
        deps = VoiceLoopDeps(
            stt=FakeSpeechToText(),
            tts=FakeTextToSpeech(),
            speaker=FakeSpeaker(),
            dialogue=DialogueEngine(FakeChatModel(), timeout_s=1, retries=0),
            text_input=FakeTextInput(list(lines)),
            audio_input=None,
        )
        return deps, {"openai_key": "set", "microphone": "not used (typed input)"}

    return factory


class FakeHost:
    def __init__(self) -> None:
        self.bodies: Mapping[str, Body] = {
            "desktop_pet": FakeBody(name="desktop_pet"),
            "fake_robot": FakeBody(name="fake_robot"),
        }
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def config(dev_config: LoadedConfig, tmp_path: Path) -> LoadedConfig:
    app = app_with(
        dev_config.app,
        tts_cache={"dir": tmp_path / "tts"},
        bodies={"connect_wait_s": 0},
        server={"port": 0},  # any free port (real server test)
    )
    return replace(dev_config, app=app)


def folder(loaded: LoadedConfig) -> Path:
    (only,) = list(loaded.app.logging.dir.iterdir())
    return only


async def test_terminal_commands_drive_a_session(dev_config: LoadedConfig, tmp_path: Path) -> None:
    loaded = config(dev_config, tmp_path)
    host = FakeHost()
    output: list[str] = []
    summary = await run_session(
        loaded,
        SessionAppOptions(participant_id="P05", typed_input=True),
        deps_factory=fake_deps(["/help", "/goto nowhere", "/end"]),
        body_host_factory=lambda *_: host,
        emit=output.append,
    )
    assert summary["end_reason"] == "completed" and summary["final_phase"] == "END"
    assert host.started and host.stopped
    assert any("Experimenter commands" in line for line in output)
    assert any("[woz] goto_phase:" in line and "must be one of" in line for line in output)
    events = (folder(loaded) / "events.jsonl").read_text("utf-8")
    assert '"woz_action"' in events and '"session_end"' in events
    assert FAKE_API_KEY not in events


async def test_woz_server_factory_gets_the_controller(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    loaded = config(dev_config, tmp_path)
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_woz(backend: WozBackend, *, log: Any) -> AsyncIterator[None]:
        seen["snapshot"] = backend.snapshot()
        log("woz_server_start", {"port": 1})
        seen["entered"] = True
        yield None
        seen["exited"] = True

    summary = await run_session(
        loaded,
        SessionAppOptions(typed_input=True, persona_id="calm"),
        woz_server_factory=fake_woz,
        deps_factory=fake_deps(["/start", "/end"]),
        body_host_factory=lambda *_: FakeHost(),
        emit=lambda _: None,
    )
    assert seen["entered"] and seen["exited"]
    assert seen["snapshot"].phase == "SETUP"
    assert summary["persona"] == "calm"
    start = (folder(loaded) / "events.jsonl").read_text("utf-8").splitlines()[0]
    assert '"woz_panel": true' in start and '"auto_start": false' in start
    assert '"woz_server_start"' in (folder(loaded) / "events.jsonl").read_text("utf-8")


async def test_a_broken_woz_server_does_not_stop_the_session(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    loaded = config(dev_config, tmp_path)

    @asynccontextmanager
    async def broken(backend: WozBackend, *, log: Any) -> AsyncIterator[None]:
        raise OSError("port in use")
        yield None  # pragma: no cover

    output: list[str] = []
    summary = await run_session(
        loaded,
        SessionAppOptions(typed_input=True),
        woz_server_factory=broken,
        deps_factory=fake_deps(["/start", "/end"]),
        body_host_factory=lambda *_: FakeHost(),
        emit=output.append,
    )
    assert summary["end_reason"] == "completed"
    assert any("WoZ panel failed" in line for line in output)


async def test_real_body_server_starts_and_stops(dev_config: LoadedConfig, tmp_path: Path) -> None:
    loaded = config(dev_config, tmp_path)
    summary = await run_session(
        loaded,
        SessionAppOptions(typed_input=True),
        deps_factory=fake_deps(["/end"]),
        emit=lambda _: None,
    )
    assert summary["end_reason"] == "completed"
    events = (folder(loaded) / "events.jsonl").read_text("utf-8")
    assert '"server_start"' in events and '"server_stop"' in events


def test_session_without_key_exits_with_error(
    capsys: pytest.CaptureFixture[str], tmp_config_dir: Path, no_env_secrets: None
) -> None:
    cfg = tmp_config_dir / "dev.yaml"
    cfg.write_text("extends: base.yaml\nmode: dev\n", encoding="utf-8")
    assert main(["--config", str(cfg), "--session"]) == EXIT_MISSING_KEY


def _run_main_with_fake_session(
    monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def fake_run(
        loaded: LoadedConfig, options: SessionAppOptions, *, woz_server_factory: Any = None
    ) -> dict[str, Any]:
        seen["options"] = options
        seen["woz"] = woz_server_factory
        return {}

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_API_KEY)
    monkeypatch.setattr(session_app, "run_session", fake_run)
    argv = ["--config", str(CONFIG_DIR / "dev.yaml"), "--session", "--typed", *extra]
    assert main(argv) == EXIT_OK
    return seen


def test_session_flag_passes_options(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _run_main_with_fake_session(monkeypatch, ["--participant", "P03"])
    assert seen["options"] == SessionAppOptions(participant_id="P03", typed_input=True)
    assert seen["woz"] is None  # no panel unless asked: the session starts by itself


def test_woz_flag_plugs_the_panel_server_into_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipi_brain.woz_server import serve_woz

    seen = _run_main_with_fake_session(monkeypatch, ["--woz"])
    assert seen["woz"].func is serve_woz
    assert set(seen["woz"].keywords) == {"loaded"}


async def test_session_loads_the_games_and_reports_the_bang_detector(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    loaded = config(dev_config, tmp_path)
    await run_session(
        loaded,
        SessionAppOptions(participant_id="P06", typed_input=True),
        deps_factory=fake_deps(["/end"]),
        body_host_factory=lambda *_: FakeHost(),
        emit=lambda _: None,
    )
    lines = (folder(loaded) / "events.jsonl").read_text("utf-8").splitlines()
    start = json.loads(lines[0])["data"]
    assert start["games"]["built"] == ["crocodile_robot", "quick_draw", "staring", "rps_arms"]
    assert start["games"]["bang_detector"] is False  # typed session: Enter is the bang
    assert start["components"]["bang_detector"].startswith("not used (no microphone)")


async def test_a_webcam_blink_detector_is_reported_and_used_for_the_cues(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    loaded = config(dev_config, tmp_path)
    made: list[float] = []

    def webcam(games: GamesConfig) -> tuple[BlinkDetector | None, str]:
        made.append(games.staring.min_fps_for_detect)
        return FakeBlinkDetector(FakeClock()), "webcam (opens only during the staring contest)"

    await run_session(
        loaded,
        SessionAppOptions(participant_id="P07", typed_input=True),
        deps_factory=fake_deps(["/end"]),
        body_host_factory=lambda *_: FakeHost(),
        blink_factory=webcam,
        emit=lambda _: None,
    )
    start = json.loads((folder(loaded) / "events.jsonl").read_text("utf-8").splitlines()[0])["data"]
    assert made == [10]  # games.yaml staring.min_fps_for_detect
    assert start["games"]["blink_detector"] is True
    assert start["components"]["blink_detector"].startswith("webcam")
    assert start["cue_checklist"]["robot_camera"] == "webcam"


async def test_no_camera_option_never_builds_a_detector(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    # e.g. a participant who does not want to be on camera: the staring contest pretends
    loaded = config(dev_config, tmp_path)

    def must_not_build(games: GamesConfig) -> tuple[BlinkDetector | None, str]:
        raise AssertionError("the webcam detector must not be built with --no-camera")

    await run_session(
        loaded,
        SessionAppOptions(participant_id="P08", typed_input=True, camera=False),
        deps_factory=fake_deps(["/end"]),
        body_host_factory=lambda *_: FakeHost(),
        blink_factory=must_not_build,
        emit=lambda _: None,
    )
    start = json.loads((folder(loaded) / "events.jsonl").read_text("utf-8").splitlines()[0])["data"]
    assert start["games"]["blink_detector"] is False
    assert start["components"]["blink_detector"].startswith("off (--no-camera)")
    assert start["cue_checklist"]["robot_camera"] == "none"


def test_without_the_vision_packages_there_is_no_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_app, "vision_installed", lambda: False)
    games = load_game_setup(load_config(CONFIG_DIR / "dev.yaml").app.games).config

    detector, status = session_app.build_blink_detector(games)

    assert detector is None and "pretend" in status and ".[vision]" in status


async def test_broken_games_file_stops_the_session_before_it_starts(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    broken = tmp_path / "games.yaml"
    broken.write_text("good_sport: maybe\n", encoding="utf-8")
    loaded = config(dev_config, tmp_path)
    app = app_with(loaded.app, games={"games_file": broken})
    host = FakeHost()
    with pytest.raises(ConfigError, match="Invalid games config"):
        await run_session(
            replace(loaded, app=app),
            SessionAppOptions(typed_input=True),
            deps_factory=fake_deps(["/end"]),
            body_host_factory=lambda *_: host,
            emit=lambda _: None,
        )
    assert not host.started and not loaded.app.logging.dir.exists()  # nothing was started
