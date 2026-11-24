from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import SecretStr

from pipi_brain.config import LoadedConfig, Secrets, load_config
from pipi_brain.dialogue.content import DialogueContent, load_dialogue_content

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PROTOCOL_FIXTURE = REPO_ROOT / "shared" / "fixtures" / "protocol_examples.json"
FAKE_API_KEY = "sk-test-FAKE-key-not-real"


@pytest.fixture
def no_env_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure real secrets from the developer's shell never leak into a test."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WOZ_TOKEN", raising=False)
    monkeypatch.delenv("RIDK_REALM", raising=False)


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """A copy of base.yaml in a temp folder, with env_file pointing to a temp .env."""
    base = (CONFIG_DIR / "base.yaml").read_text(encoding="utf-8")
    base = base.replace("env_file: ../.env", "env_file: test.env")
    (tmp_path / "base.yaml").write_text(base, encoding="utf-8")
    return tmp_path


@pytest.fixture
def dev_config(tmp_path: Path) -> LoadedConfig:
    """dev.yaml with logs redirected to a temp folder and a fake API key (never a real one)."""
    loaded = load_config(CONFIG_DIR / "dev.yaml")
    app = loaded.app.model_copy(
        update={"logging": loaded.app.logging.model_copy(update={"dir": tmp_path / "logs"})}
    )
    secrets = Secrets(openai_api_key=SecretStr(FAKE_API_KEY), woz_token=None)
    return replace(loaded, app=app, secrets=secrets)


@pytest.fixture
def dialogue_content(dev_config: LoadedConfig) -> DialogueContent:
    return load_dialogue_content(dev_config.app.dialogue)
