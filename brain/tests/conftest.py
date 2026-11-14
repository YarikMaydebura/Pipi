from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PROTOCOL_FIXTURE = REPO_ROOT / "shared" / "fixtures" / "protocol_examples.json"


@pytest.fixture
def no_env_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure real secrets from the developer's shell never leak into a test."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WOZ_TOKEN", raising=False)


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """A copy of base.yaml in a temp folder, with env_file pointing to a temp .env."""
    base = (CONFIG_DIR / "base.yaml").read_text(encoding="utf-8")
    base = base.replace("env_file: ../.env", "env_file: test.env")
    (tmp_path / "base.yaml").write_text(base, encoding="utf-8")
    return tmp_path
