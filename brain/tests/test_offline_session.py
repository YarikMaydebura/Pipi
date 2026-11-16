"""The offline session tool: no API key, no network, the same session code."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.llm import LlmError
from pipi_brain.dialogue.schemas import parse_dialogue_turn
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.tools import offline_session
from pipi_brain.tools.offline_session import OfflineChatModel, main, offline_deps
from pipi_brain.voice_app import SessionOptions


async def test_offline_deps_need_no_key_and_fail_over_to_the_fallbacks(
    dev_config: LoadedConfig, no_env_secrets: None
) -> None:
    deps, health = await offline_deps(dev_config, SessionOptions(typed_input=True), AudioGate(0))
    assert deps.audio_input is None and "not used" in health["openai_key"]
    audio = await deps.tts.synthesize("Let's play Crocodile!")
    assert audio.duration_s > 0.5  # the babble voice, so the body still "talks"
    with pytest.raises(LlmError):
        await OfflineChatModel().complete_json([])
    result = await deps.dialogue.respond([], "fallback line")
    assert result.fallback_used and result.turn.say == "fallback line"
    asked = await deps.dialogue.ask([], parse_dialogue_turn)
    assert asked.value is None and "offline" in asked.errors[0]
    await deps.speaker.play(audio)
    deps.speaker.stop()


def test_offline_main_reports_a_bad_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(tmp_path / "nope.yaml")]) == 2
    assert "Config error" in capsys.readouterr().err


def test_offline_main_runs_the_normal_session_with_offline_deps(
    monkeypatch: pytest.MonkeyPatch, dev_config: LoadedConfig
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_session(loaded: LoadedConfig, options: object, **kwargs: object) -> dict:
        seen.update(loaded=loaded, options=options, **kwargs)
        return {}

    monkeypatch.setattr(offline_session, "run_session", fake_run_session)
    assert main(["--config", str(dev_config.source)]) == 0
    loaded = seen["loaded"]
    assert isinstance(loaded, LoadedConfig) and loaded.app.tts_cache.enabled is False
    assert seen["deps_factory"] is offline_deps
    assert seen["options"].typed_input is True  # type: ignore[attr-defined]
