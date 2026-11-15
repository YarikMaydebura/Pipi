"""Config sections added in M1: persona, dialogue, audio, vad, timeouts."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipi_brain.config import ConfigError, load_config
from pipi_brain.dialogue.content import load_dialogue_content

from .conftest import CONFIG_DIR, REPO_ROOT


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_m1_defaults_from_base() -> None:
    app = load_config(CONFIG_DIR / "dev.yaml").app
    assert app.dialogue.reasoning_effort == "minimal"
    assert app.dialogue.llm_retries == 1
    assert app.audio.sample_rate == 16000
    assert app.audio.frame_samples == 512
    assert app.audio.gate_tail_ms == 300
    assert app.vad.engine == "silero"
    assert app.vad.end_silence_ms == 700
    assert app.vad.max_utterance_s == 15
    assert app.timeouts.stt_s == 6 and app.timeouts.llm_s == 6


def test_new_paths_are_resolved_relative_to_the_config_file() -> None:
    app = load_config(CONFIG_DIR / "dev.yaml").app
    assert app.dialogue.personas_file == CONFIG_DIR / "personas.yaml"
    assert app.dialogue.lines_file == CONFIG_DIR / "lines.yaml"
    assert app.dialogue.prompts_dir == CONFIG_DIR / "prompts"
    assert app.vad.model_path == REPO_ROOT / "cache" / "silero_vad.onnx"


def test_8khz_uses_256_sample_frames(tmp_config_dir: Path) -> None:
    cfg = _write(
        tmp_config_dir / "dev.yaml", "extends: base.yaml\nmode: dev\naudio:\n  sample_rate: 8000\n"
    )
    assert load_config(cfg).app.audio.frame_samples == 256


@pytest.mark.parametrize(
    "override",
    [
        "audio:\n  sample_rate: 44100\n",  # Silero supports only 8k / 16k
        "dialogue:\n  reasoning_effort: turbo\n",
        "vad:\n  threshold: 1.5\n",
        "vad:\n  model_url: http://insecure.example/model.onnx\n",
        "vad:\n  model_sha256: not-a-hash\n",
        "timeouts:\n  llm_s: 0\n",
    ],
)
def test_invalid_m1_values_are_rejected(tmp_config_dir: Path, override: str) -> None:
    cfg = _write(tmp_config_dir / "bad.yaml", f"extends: base.yaml\nmode: dev\n{override}")
    with pytest.raises(ConfigError):
        load_config(cfg)


@pytest.mark.parametrize("mode", ["dev", "study", "demo"])
def test_default_persona_exists_and_all_prompts_load(mode: str) -> None:
    app = load_config(CONFIG_DIR / f"{mode}.yaml").app
    content = load_dialogue_content(app.dialogue)
    assert content.persona(app.persona.default).id == app.persona.default
    assert {"GREETING", "CHAT"} <= set(content.phase_prompts)


def test_every_line_used_by_the_voice_loop_exists() -> None:
    content = load_dialogue_content(load_config(CONFIG_DIR / "dev.yaml").app.dialogue)
    for line_id in ("opening", "stt_retry", "llm_fallback", "silence_reprompt", "goodbye"):
        for persona in content.personas:
            assert content.line(line_id, persona)
