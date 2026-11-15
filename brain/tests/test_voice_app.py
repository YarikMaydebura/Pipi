"""Whole terminal session with fake dependencies, and the --voice-loop entry point."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from pipi_brain import voice_app
from pipi_brain.__main__ import EXIT_MISSING_KEY, EXIT_OK, main
from pipi_brain.config import ConfigError, LoadedConfig, Secrets
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.fakes import (
    FakeChatModel,
    FakeSpeaker,
    FakeSpeechToText,
    FakeTextInput,
    FakeTextToSpeech,
)
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.voice_app import SessionOptions, build_real_deps, run_voice_session
from pipi_brain.voice_loop import VoiceLoopDeps

from .conftest import CONFIG_DIR, FAKE_API_KEY

REPLY = json.dumps({"say": "Hi Lena!", "memory_updates": {"name": "Lena"}})


class _NeverTyped:
    async def read_line(self) -> str | None:
        await asyncio.sleep(3600)
        return None


def fake_factory(text_input: Any = None) -> Any:
    async def factory(
        loaded: LoadedConfig, options: SessionOptions, gate: AudioGate
    ) -> tuple[VoiceLoopDeps, dict[str, str]]:
        deps = VoiceLoopDeps(
            stt=FakeSpeechToText(),
            tts=FakeTextToSpeech(),
            speaker=FakeSpeaker(),
            dialogue=DialogueEngine(FakeChatModel([REPLY]), timeout_s=1, retries=1),
            text_input=text_input or FakeTextInput(["I'm Lena", "/quit"]),
            audio_input=None,
        )
        return deps, {"openai_key": "set", "microphone": "not used (typed input)"}

    return factory


def _session_folder(loaded: LoadedConfig) -> Path:
    (folder,) = list(loaded.app.logging.dir.iterdir())
    return folder


async def test_full_typed_session_writes_a_complete_log(dev_config: LoadedConfig) -> None:
    output: list[str] = []
    summary = await run_voice_session(
        dev_config,
        SessionOptions(participant_id="P07", typed_input=True),
        deps_factory=fake_factory(),
        emit=output.append,
    )
    folder = _session_folder(dev_config)
    assert folder.name.startswith("P07_")
    events = [
        json.loads(line) for line in (folder / "events.jsonl").read_text("utf-8").splitlines()
    ]
    types = [e["type"] for e in events]
    assert types[:3] == ["session_start", "health_check", "persona_choice"]
    assert types[-1] == "session_end"
    start = events[0]["data"]
    assert start["config_hash"] == dev_config.config_hash
    assert start["persona"] == "cheerful" and start["input"] == "typed"
    assert start["models"]["dialogue"] == "gpt-5-nano"
    assert start["cue_checklist"]["same_voice"] is True
    assert summary["end_reason"] == "completed" and summary["user_turns"] == 1
    assert json.loads((folder / "memory.json").read_text("utf-8"))["name"] == "Lena"
    assert (folder / "summary.json").is_file()
    assert any("Type to Pipi" in line for line in output)


async def test_api_key_never_reaches_logs_or_output(dev_config: LoadedConfig) -> None:
    output: list[str] = []
    await run_voice_session(
        dev_config, SessionOptions(), deps_factory=fake_factory(), emit=output.append
    )
    for file in _session_folder(dev_config).iterdir():
        assert FAKE_API_KEY not in file.read_text("utf-8")
    assert all(FAKE_API_KEY not in line for line in output)


async def test_interrupted_session_still_writes_summary(dev_config: LoadedConfig) -> None:
    task = asyncio.create_task(
        run_voice_session(
            dev_config,
            SessionOptions(),
            deps_factory=fake_factory(_NeverTyped()),
            emit=lambda _: None,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    summary = json.loads((_session_folder(dev_config) / "summary.json").read_text("utf-8"))
    assert summary["end_reason"] == "interrupted"


async def test_unknown_persona_is_rejected_before_starting(dev_config: LoadedConfig) -> None:
    with pytest.raises(ConfigError, match="grumpy"):
        await run_voice_session(
            dev_config, SessionOptions(persona_id="grumpy"), deps_factory=fake_factory()
        )
    assert not dev_config.app.logging.dir.exists()


async def test_real_deps_need_an_api_key(dev_config: LoadedConfig) -> None:
    from dataclasses import replace

    no_key = replace(dev_config, secrets=Secrets(openai_api_key=None, woz_token=None))
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        await build_real_deps(no_key, SessionOptions(typed_input=True), AudioGate(0))


async def test_real_deps_in_typed_mode_open_no_microphone(dev_config: LoadedConfig) -> None:
    # Building the client makes no network call; typed mode never touches audio input.
    deps, health = await build_real_deps(dev_config, SessionOptions(typed_input=True), AudioGate(0))
    assert deps.audio_input is None
    assert health["microphone"].startswith("not used")


def test_voice_loop_without_key_exits_with_error(
    capsys: pytest.CaptureFixture[str], tmp_config_dir: Path, no_env_secrets: None
) -> None:
    cfg = tmp_config_dir / "dev.yaml"
    cfg.write_text("extends: base.yaml\nmode: dev\n", encoding="utf-8")
    assert main(["--config", str(cfg), "--voice-loop"]) == EXIT_MISSING_KEY
    assert "OPENAI_API_KEY is missing" in capsys.readouterr().err


def test_voice_loop_flag_passes_options(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(loaded: LoadedConfig, options: SessionOptions) -> dict[str, Any]:
        seen["options"] = options
        return {}

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_API_KEY)
    monkeypatch.setattr(voice_app, "run_voice_session", fake_run)
    argv = [
        "--config",
        str(CONFIG_DIR / "dev.yaml"),
        "--voice-loop",
        "--typed",
        "--participant",
        "P02",
        "--persona",
        "witty",
        "--max-turns",
        "3",
    ]
    assert main(argv) == EXIT_OK
    assert seen["options"] == SessionOptions(
        participant_id="P02", persona_id="witty", typed_input=True, max_user_turns=3
    )
    assert FAKE_API_KEY not in capsys.readouterr().out
