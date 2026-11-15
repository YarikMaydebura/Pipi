"""pet_cli commands, the babble voice, and ``--voice-loop --body pet`` without a pet."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from pipi_brain import voice_app
from pipi_brain.__main__ import EXIT_OK, main
from pipi_brain.config import LoadedConfig
from pipi_brain.fakes import FakeBody
from pipi_brain.speech.audio_utils import pcm16_to_float
from pipi_brain.tools.babble import babble
from pipi_brain.tools.pet_cli import PetCli
from pipi_brain.voice_app import SessionOptions, run_voice_session

from .conftest import CONFIG_DIR, FAKE_API_KEY
from .test_voice_app import fake_factory


async def test_pet_cli_sends_each_command_to_the_body() -> None:
    body = FakeBody()
    cli = PetCli(body)
    assert (await cli.execute("eyes happy")).startswith("ok")  # type: ignore[union-attr]
    await cli.execute("motion wave")
    await cli.execute("caption Break time!")
    await cli.execute("caption")
    await cli.execute("out")
    await cli.execute("in wake_up")
    assert body.calls == [
        ("eyes", "happy"),
        ("motion", "wave"),
        ("caption", "Break time!"),
        ("caption", None),
        ("deactivate", "jump_out"),
        ("activate", "wake_up"),
    ]


async def test_pet_cli_say_uses_babble_audio_and_text_has_none() -> None:
    body = FakeBody()
    cli = PetCli(body)
    reply = await cli.execute("say Hello there")
    assert reply is not None and reply.startswith("spoken")
    await cli.execute("text Only words")
    assert body.spoken[0][1] is not None and body.spoken[1][1] is None


async def test_pet_cli_validates_input_and_quits() -> None:
    body = FakeBody(connected=False)
    cli = PetCli(body)
    assert "must be one of" in (await cli.execute("eyes rainbow") or "")
    assert "must be one of" in (await cli.execute("out teleport") or "")
    assert "unknown command" in (await cli.execute("dance") or "")
    assert "failed: not connected" in (await cli.execute("motion nod") or "")
    assert "not delivered" in (await cli.execute("say hi") or "")
    assert "not connected" in (await cli.execute("status") or "")
    assert await cli.execute("") == ""
    assert await cli.execute("quit") is None
    assert body.calls == [("motion", "nod"), ("speak", "hi")]


def test_babble_sounds_like_syllables() -> None:
    audio = babble("Hello there, how are you?")
    samples = pcm16_to_float(audio.pcm16)
    assert audio.sample_rate == 24000
    assert audio.duration_s == pytest.approx(25 / 14, rel=0.01)
    frames = samples[: len(samples) // 1200 * 1200].reshape(-1, 1200)  # 50 ms frames
    loudness = np.sqrt(np.mean(frames**2, axis=1))
    assert loudness.max() > 0.05 and loudness.min() < 0.01  # loud syllables and pauses
    assert babble("").duration_s == pytest.approx(0.6)


async def test_voice_loop_with_pet_body_runs_without_a_pet(dev_config: LoadedConfig) -> None:
    app = dev_config.app
    app = app.model_copy(
        update={
            "server": app.server.model_copy(update={"port": 0}),
            "bodies": app.bodies.model_copy(update={"connect_wait_s": 0.05}),
        }
    )
    loaded = dev_config.__class__(
        app=app,
        secrets=dev_config.secrets,
        source=dev_config.source,
        config_hash=dev_config.config_hash,
    )
    output: list[str] = []
    summary = await run_voice_session(
        loaded,
        SessionOptions(typed_input=True, body="pet"),
        deps_factory=fake_factory(),
        emit=output.append,
    )
    assert summary["end_reason"] == "completed"
    (folder,) = list(app.logging.dir.iterdir())
    events = [
        json.loads(line) for line in (folder / "events.jsonl").read_text("utf-8").splitlines()
    ]
    types = [e["type"] for e in events]
    assert "server_start" in types and "server_stop" in types
    assert events[0]["data"]["output_body"] == "desktop_pet"
    health = next(e for e in events if e["type"] == "health_check")["data"]
    assert health["desktop_pet"] == "not connected"
    fallbacks = [e for e in events if e["type"] == "body_fallback"]
    assert len(fallbacks) == 2 and fallbacks[0]["body"] == "desktop_pet"
    assert any("no desktop pet yet" in line for line in output)


def test_body_flag_reaches_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(loaded: LoadedConfig, options: SessionOptions) -> dict[str, Any]:
        seen["options"] = options
        return {}

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_API_KEY)
    monkeypatch.setattr(voice_app, "run_voice_session", fake_run)
    argv = ["--config", str(CONFIG_DIR / "dev.yaml"), "--voice-loop", "--typed", "--body", "pet"]
    assert main(argv) == EXIT_OK
    assert seen["options"].body == "pet"
