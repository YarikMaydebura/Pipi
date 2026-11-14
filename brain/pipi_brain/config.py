"""Configuration: YAML files in ``config/`` plus secrets from ``.env``.

How loading works:
1. Read the mode file (e.g. ``config/dev.yaml``).
2. If it has ``extends: base.yaml``, read that file first and deep-merge the mode file on top.
   So ``base.yaml`` holds every default and mode files only hold what differs.
3. Validate the merged result with pydantic. Unknown keys are errors (typos fail loudly).
4. Read secrets (``OPENAI_API_KEY``, ``WOZ_TOKEN``) from the environment, falling back to the
   ``.env`` file. Secrets are ``SecretStr`` so they never show up when printed.

All relative paths in YAML are resolved relative to the YAML file itself, so the brain behaves
the same no matter which folder it is started from (Windows and macOS).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

# Hard constraint from the course: these are the ONLY models we may call.
ALLOWED_MODELS: Mapping[str, frozenset[str]] = {
    "dialogue": frozenset({"gpt-5-nano"}),
    "stt": frozenset({"gpt-4o-mini-transcribe"}),
    "tts": frozenset({"tts-1"}),
}

EXTENDS_KEY = "extends"
MAX_EXTENDS_DEPTH = 3


class ConfigError(Exception):
    """Raised when a config file is missing, unreadable or invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerConfig(_Section):
    host: str
    port: int = Field(ge=1024, le=65535)


class PetConfig(_Section):
    robot_side: Literal["left", "right"]


class RobotConfig(_Section):
    body: Literal["fake_robot", "alpha_mini"]


class TimersConfig(_Section):
    focus_s: int = Field(gt=0)
    focus_precue_s: int = Field(gt=0)
    break_max_s: int | None = Field(default=None, gt=0)  # None = no limit (demo mode)
    silence_reprompt_s: int = Field(gt=0)


class ModelsConfig(_Section):
    dialogue: str
    stt: str
    tts: str
    tts_voice: Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    @field_validator("dialogue", "stt", "tts")
    @classmethod
    def _only_allowed_models(cls, value: str, info: ValidationInfo) -> str:
        allowed = ALLOWED_MODELS[info.field_name]
        if value not in allowed:
            raise ValueError(
                f"model '{value}' is not allowed for {info.field_name}; "
                f"course rules allow only: {', '.join(sorted(allowed))}"
            )
        return value


class LoggingConfig(_Section):
    dir: Path
    save_audio: bool
    verbose: bool


class CuesConfig(_Section):
    """Identity cues we intend to show. The actual state is logged at session start."""

    same_eyes: bool
    same_voice: bool
    signature_phrase: bool
    signature_gesture: bool
    memory_references: bool
    transition_animation: bool


class AppConfig(_Section):
    mode: Literal["dev", "study", "demo"]
    env_file: Path
    server: ServerConfig
    pet: PetConfig
    robot: RobotConfig
    timers: TimersConfig
    models: ModelsConfig
    logging: LoggingConfig
    cues: CuesConfig


class Secrets(_Section):
    openai_api_key: SecretStr | None
    woz_token: SecretStr | None


@dataclass(frozen=True)
class LoadedConfig:
    app: AppConfig
    secrets: Secrets
    source: Path
    config_hash: str  # short hash of the merged YAML, written to each session log


def load_config(path: Path | str) -> LoadedConfig:
    """Load, merge and validate a config file. Raises ConfigError with a readable message."""
    source = Path(path).expanduser().resolve()
    merged = _read_with_extends(source, depth=0)
    resolved = _resolve_paths(merged, base_dir=source.parent)
    try:
        app = AppConfig.model_validate(resolved)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config in {source}:\n{exc}") from exc
    return LoadedConfig(
        app=app,
        secrets=_read_secrets(app.env_file),
        source=source,
        config_hash=_hash(merged),
    )


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict: ``override`` merged into ``base`` (nested dicts merged, rest replaced)."""
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file {path} is not valid YAML:\n{exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a mapping at the top level")
    return data


def _read_with_extends(path: Path, depth: int) -> dict[str, Any]:
    if depth > MAX_EXTENDS_DEPTH:
        raise ConfigError(f"Too many nested '{EXTENDS_KEY}' levels at {path}")
    data = _read_yaml(path)
    parent_name = data.get(EXTENDS_KEY)
    own = {k: v for k, v in data.items() if k != EXTENDS_KEY}
    if parent_name is None:
        return own
    if not isinstance(parent_name, str):
        raise ConfigError(f"'{EXTENDS_KEY}' in {path} must be a file name")
    parent = _read_with_extends(path.parent / parent_name, depth + 1)
    return deep_merge(parent, own)


def _resolve_paths(data: Mapping[str, Any], base_dir: Path) -> dict[str, Any]:
    """Make the known path fields absolute, relative to the config file's folder."""
    result = dict(data)
    if isinstance(result.get("env_file"), str):
        result["env_file"] = (base_dir / result["env_file"]).resolve()
    logging_section = result.get("logging")
    if isinstance(logging_section, Mapping) and isinstance(logging_section.get("dir"), str):
        result["logging"] = {
            **logging_section,
            "dir": (base_dir / logging_section["dir"]).resolve(),
        }
    return result


def _read_secrets(env_file: Path) -> Secrets:
    """Environment variables win over the .env file. Empty values count as missing."""
    file_values = dotenv_values(env_file) if env_file.is_file() else {}

    def lookup(name: str) -> SecretStr | None:
        value = os.environ.get(name) or file_values.get(name) or ""
        value = value.strip()
        return SecretStr(value) if value else None

    return Secrets(openai_api_key=lookup("OPENAI_API_KEY"), woz_token=lookup("WOZ_TOKEN"))


def _hash(data: Mapping[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:12]
