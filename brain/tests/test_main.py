from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pipi_brain.__main__ import EXIT_CONFIG_ERROR, EXIT_OK, main

from .conftest import CONFIG_DIR

FAKE_KEY = "sk-test-SECRET-do-not-print"


def test_entry_point_prints_summary_and_exits_ok(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    exit_code = main(["--config", str(CONFIG_DIR / "dev.yaml")])
    out = capsys.readouterr()
    assert exit_code == EXIT_OK
    assert "mode          : dev" in out.out
    assert "OPENAI_API_KEY: set" in out.out


def test_api_key_never_appears_in_any_output(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("WOZ_TOKEN", "woz-SECRET-token")
    for mode in ("dev", "study", "demo"):
        main(["--config", str(CONFIG_DIR / f"{mode}.yaml")])
    out = capsys.readouterr()
    for secret in (FAKE_KEY, "woz-SECRET-token", "SECRET"):
        assert secret not in out.out
        assert secret not in out.err


def test_missing_key_prints_warning(
    capsys: pytest.CaptureFixture[str], tmp_config_dir: Path, no_env_secrets: None
) -> None:
    cfg = tmp_config_dir / "dev.yaml"
    cfg.write_text("extends: base.yaml\nmode: dev\n", encoding="utf-8")
    assert main(["--config", str(cfg)]) == EXIT_OK
    out = capsys.readouterr()
    assert "OPENAI_API_KEY: missing" in out.out
    assert "Warning" in out.err


def test_bad_config_exits_with_error_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["--config", str(tmp_path / "missing.yaml")]) == EXIT_CONFIG_ERROR
    assert "Config error" in capsys.readouterr().err


def test_python_dash_m_runs_from_any_folder(tmp_path: Path) -> None:
    """The real command a user types, started from an unrelated working directory."""
    result = subprocess.run(
        [sys.executable, "-m", "pipi_brain", "--config", str(CONFIG_DIR / "dev.yaml")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == EXIT_OK, result.stderr
    assert "Pipi brain" in result.stdout
