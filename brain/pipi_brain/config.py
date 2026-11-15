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
    "tts": frozenset({"gpt-4o-mini-tts"}),
}

EXTENDS_KEY = "extends"

# (section, key) pairs holding paths; resolved relative to the YAML file that is loaded.
PATH_FIELDS: tuple[tuple[str, str], ...] = (
    ("logging", "dir"),
    ("dialogue", "personas_file"),
    ("dialogue", "lines_file"),
    ("dialogue", "prompts_dir"),
    ("vad", "model_path"),
    ("woz", "web_dist"),
    ("session", "reading_text_file"),
    ("tts_cache", "dir"),
)
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


class BodiesConfig(_Section):
    """WebSocket bodies (desktop pet, fake robot): how long the brain waits for them."""

    hello_timeout_s: float = Field(gt=0)  # a new connection must send `hello` within this
    ack_timeout_s: float = Field(gt=0)  # every command must be acked within this
    ack_retries: int = Field(ge=0, le=3)  # resend harmless commands (eyes, caption) this often
    migration_timeout_s: float = Field(gt=0)  # activate/deactivate ack after the animation
    speech_done_margin_s: float = Field(ge=0)  # speech_done wait = audio length + this
    caption_s_per_char: float = Field(gt=0)  # no-audio speech: estimated reading time
    connect_wait_s: float = Field(ge=0)  # `--body pet`: wait this long for the pet at start


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


ReasoningEffort = Literal["minimal", "low", "medium", "high"]


class PersonaConfig(_Section):
    default: str = Field(min_length=1)  # must be an id from personas_file
    allow_choice: bool


class DialogueConfig(_Section):
    """LLM turn settings and where the persona presets, fixed lines and phase prompts live."""

    personas_file: Path
    lines_file: Path
    prompts_dir: Path
    reasoning_effort: ReasoningEffort  # gpt-5-nano is a reasoning model: lowest = fastest
    max_output_tokens: int = Field(ge=64, le=8000)  # includes the model's reasoning tokens
    history_turns: int = Field(ge=0, le=50)  # recent turns sent as context
    llm_retries: int = Field(ge=0, le=3)  # extra attempts after invalid JSON / error


class AudioConfig(_Section):
    sample_rate: Literal[8000, 16000]  # Silero VAD only supports these two rates
    input_device: str | int | None  # None = system default; else device name or index
    output_device: str | int | None
    gate_tail_ms: int = Field(ge=0, le=5000)  # mic stays closed this long after Pipi speaks
    mic_frame_timeout_s: float = Field(gt=0)  # no audio for this long = microphone failure

    @property
    def frame_samples(self) -> int:
        """Samples per VAD frame: Silero needs 512 @ 16 kHz and 256 @ 8 kHz (32 ms)."""
        return 512 if self.sample_rate == 16000 else 256


class VadConfig(_Section):
    engine: Literal["silero", "energy"]  # energy = simple loudness fallback, no model needed
    threshold: float = Field(gt=0, lt=1)  # speech probability that starts an utterance
    end_silence_ms: int = Field(ge=100, le=5000)
    min_speech_ms: int = Field(ge=0, le=5000)  # shorter blips (coughs, clicks) are dropped
    pre_roll_ms: int = Field(ge=0, le=2000)  # audio kept from just before speech started
    max_utterance_s: float = Field(gt=0, le=60)
    energy_threshold_dbfs: float = Field(lt=0)
    model_path: Path
    model_url: str = Field(pattern=r"^https://")
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    download_timeout_s: float = Field(gt=0)


class TimeoutsConfig(_Section):
    """Seconds before an external call is abandoned and its fallback is used."""

    stt_s: float = Field(gt=0)
    llm_s: float = Field(gt=0)  # per attempt
    tts_s: float = Field(gt=0)
    playback_margin_s: float = Field(ge=0)  # added to the audio length when waiting for playback


class WozConfig(_Section):
    """WoZ panel server (``woz_server.py``): HTTP for the built web app + the panel WebSocket."""

    host: str  # 127.0.0.1 = this laptop only; 0.0.0.0 = LAN (then WOZ_TOKEN is required)
    port: int = Field(ge=1024, le=65535)
    max_panels: int = Field(ge=1, le=10)  # concurrent panel connections
    web_dist: Path  # built web app (`npm run build`), served at /woz/ and /fake-robot/
    command_timeout_s: float = Field(gt=0)  # ack ok=false if a command takes longer


class SessionConfig(_Section):
    """The full session flow (``phases/``, docs/INTERACTION_FLOW.md): limits in seconds."""

    persona_pick_s: float = Field(gt=0)  # no choice within this -> persona.default
    greeting_max_turns: int = Field(ge=1, le=20)  # participant answers before FOCUS anyway
    greeting_max_s: float = Field(gt=0)
    chat_max_exchanges: int = Field(ge=1, le=10)  # CHAT: participant answers, then the game
    chat_max_s: float = Field(gt=0)
    game_menu_s: float = Field(gt=0)  # no clear choice within this -> default_game
    default_game: str = Field(min_length=1)  # id from games/registry.py
    game_placeholder_s: float = Field(gt=0)  # M3 placeholder games last this long
    game_loop: bool  # demo: GAME_CHOSEN -> GAME_MENU until the participant says stop
    return_end_s: float | None = Field(default=None, gt=0)  # RETURN -> END; null = WoZ ends
    flight_s: float = Field(ge=0, le=5)  # silence between jump_out and the robot waking up
    robot_connect_wait_s: float = Field(ge=0)  # migration waits this long for the robot
    thinking_delay_ms: int = Field(ge=0, le=5000)  # thinking eyes if a reply takes longer
    health_poll_s: float = Field(gt=0)  # body health check interval (WoZ state + alerts)
    reading_text_file: Path | None = None  # FOCUS word help context (study text, M6)


class TtsCacheConfig(_Section):
    """Fixed lines' speech cached on disk (gitignored), pre-warmed at session start."""

    enabled: bool
    dir: Path
    prewarm_timeout_s: float = Field(gt=0)
    prewarm_concurrency: int = Field(ge=1, le=8)


class AppConfig(_Section):
    mode: Literal["dev", "study", "demo"]
    env_file: Path
    server: ServerConfig
    pet: PetConfig
    bodies: BodiesConfig
    robot: RobotConfig
    timers: TimersConfig
    models: ModelsConfig
    persona: PersonaConfig
    dialogue: DialogueConfig
    audio: AudioConfig
    vad: VadConfig
    timeouts: TimeoutsConfig
    logging: LoggingConfig
    cues: CuesConfig
    woz: WozConfig
    session: SessionConfig
    tts_cache: TtsCacheConfig


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


def read_yaml(path: Path) -> dict[str, Any]:
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
    data = read_yaml(path)
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
    for section_name, key in PATH_FIELDS:
        section = result.get(section_name)
        if isinstance(section, Mapping) and isinstance(section.get(key), str):
            result[section_name] = {**section, key: (base_dir / section[key]).resolve()}
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
