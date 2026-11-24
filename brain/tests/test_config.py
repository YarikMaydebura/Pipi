from __future__ import annotations

from pathlib import Path

import pytest

from pipi_brain.config import ConfigError, deep_merge, load_config

from .conftest import CONFIG_DIR, REPO_ROOT


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("mode", ["dev", "study", "demo"])
def test_every_mode_file_loads(mode: str) -> None:
    loaded = load_config(CONFIG_DIR / f"{mode}.yaml")
    assert loaded.app.mode == mode


def test_dev_overrides_base_but_keeps_other_defaults() -> None:
    app = load_config(CONFIG_DIR / "dev.yaml").app
    assert app.timers.focus_s == 30  # from dev.yaml
    assert app.timers.silence_reprompt_s == 12  # inherited from base.yaml
    assert app.models.dialogue == "gpt-5-nano"


def test_study_uses_fixed_four_minute_focus_and_real_robot() -> None:
    app = load_config(CONFIG_DIR / "study.yaml").app
    assert app.timers.focus_s == 240
    assert app.timers.break_max_s == 300
    assert app.robot.body == "alpha_mini"


def test_demo_has_no_break_limit() -> None:
    assert load_config(CONFIG_DIR / "demo.yaml").app.timers.break_max_s is None


def test_paths_are_resolved_relative_to_the_config_file() -> None:
    app = load_config(CONFIG_DIR / "dev.yaml").app
    assert app.logging.dir == REPO_ROOT / "logs"
    assert app.env_file == REPO_ROOT / ".env"


def test_unknown_key_is_rejected(tmp_config_dir: Path) -> None:
    cfg = _write(tmp_config_dir / "typo.yaml", "extends: base.yaml\nmode: dev\ntimerz: {}\n")
    with pytest.raises(ConfigError, match="timerz"):
        load_config(cfg)


@pytest.mark.parametrize(
    ("section_key", "bad_model"),
    [("dialogue", "gpt-4o"), ("stt", "whisper-1"), ("tts", "tts-1")],
)
def test_disallowed_model_is_rejected(
    tmp_config_dir: Path, section_key: str, bad_model: str
) -> None:
    cfg = _write(
        tmp_config_dir / "bad_model.yaml",
        f"extends: base.yaml\nmode: dev\nmodels:\n  {section_key}: {bad_model}\n",
    )
    with pytest.raises(ConfigError, match="not allowed"):
        load_config(cfg)


def test_missing_file_gives_readable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_gives_readable_error(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "broken.yaml", "mode: [dev\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(cfg)


def test_missing_api_key_is_reported_as_none(tmp_config_dir: Path, no_env_secrets: None) -> None:
    cfg = _write(tmp_config_dir / "dev.yaml", "extends: base.yaml\nmode: dev\n")
    assert load_config(cfg).secrets.openai_api_key is None


def test_api_key_is_read_from_env_file(tmp_config_dir: Path, no_env_secrets: None) -> None:
    _write(tmp_config_dir / "test.env", "OPENAI_API_KEY=sk-from-file\nWOZ_TOKEN=abc\n")
    cfg = _write(tmp_config_dir / "dev.yaml", "extends: base.yaml\nmode: dev\n")
    secrets = load_config(cfg).secrets
    assert secrets.openai_api_key is not None
    assert secrets.openai_api_key.get_secret_value() == "sk-from-file"
    assert "sk-from-file" not in repr(secrets)  # SecretStr hides the value


def test_ridk_realm_is_a_secret_read_from_env_file(
    tmp_config_dir: Path, no_env_secrets: None
) -> None:
    # Whoever has the realm controls the robot: same handling as the API key.
    _write(tmp_config_dir / "test.env", "RIDK_REALM=rie.0123abcd\n")
    cfg = _write(tmp_config_dir / "dev.yaml", "extends: base.yaml\nmode: dev\n")
    loaded = load_config(cfg)
    assert loaded.secrets.ridk_realm is not None
    assert loaded.secrets.ridk_realm.get_secret_value() == "rie.0123abcd"
    assert "rie.0123abcd" not in repr(loaded.secrets)
    assert loaded.app.robot.ridk_url.startswith("ws")


def test_environment_variable_wins_over_env_file(
    tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_config_dir / "test.env", "OPENAI_API_KEY=sk-from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    cfg = _write(tmp_config_dir / "dev.yaml", "extends: base.yaml\nmode: dev\n")
    key = load_config(cfg).secrets.openai_api_key
    assert key is not None and key.get_secret_value() == "sk-from-env"


def test_config_hash_changes_when_config_changes(tmp_config_dir: Path) -> None:
    a = _write(tmp_config_dir / "a.yaml", "extends: base.yaml\nmode: dev\n")
    b = _write(
        tmp_config_dir / "b.yaml", "extends: base.yaml\nmode: dev\npet: {robot_side: left}\n"
    )
    assert load_config(a).config_hash != load_config(b).config_hash


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"timers": {"focus_s": 240, "break_max_s": 300}, "mode": "dev"}
    override = {"timers": {"focus_s": 30}}
    merged = deep_merge(base, override)
    assert merged == {"timers": {"focus_s": 30, "break_max_s": 300}, "mode": "dev"}
    assert base["timers"] == {"focus_s": 240, "break_max_s": 300}
