"""Load the editable dialogue content from ``config/``: persona presets, fixed lines, prompts.

- ``personas.yaml``: tone per persona preset (cheerful / calm / witty)
- ``lines.yaml``: fixed, never-generated lines with optional per-persona variants
- ``prompts/<phase>.txt``: the phase instruction given to the LLM (e.g. ``greeting.txt``)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pipi_brain.config import ConfigError, DialogueConfig, read_yaml

DEFAULT_VARIANT = "default"


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tone: str = Field(min_length=1)


@dataclass(frozen=True)
class DialogueContent:
    personas: Mapping[str, Persona]
    lines: Mapping[str, Mapping[str, str]]  # line id -> {"default": ..., "<persona>": ...}
    phase_prompts: Mapping[str, str]  # "GREETING" -> instruction text

    def persona(self, persona_id: str) -> Persona:
        try:
            return self.personas[persona_id]
        except KeyError as exc:
            known = ", ".join(sorted(self.personas))
            raise ConfigError(f"Unknown persona {persona_id!r}; known: {known}") from exc

    def line(self, line_id: str, persona_id: str) -> str:
        """Persona variant of a fixed line, falling back to its default text."""
        variants = self.lines.get(line_id)
        if variants is None:
            raise ConfigError(f"Fixed line {line_id!r} is missing from lines.yaml")
        return variants.get(persona_id, variants[DEFAULT_VARIANT])

    def phase_instruction(self, phase: str) -> str:
        try:
            return self.phase_prompts[phase]
        except KeyError as exc:
            raise ConfigError(
                f"No prompt for phase {phase}; add prompts/{phase.lower()}.txt"
            ) from exc


def load_dialogue_content(config: DialogueConfig) -> DialogueContent:
    return DialogueContent(
        personas=_load_personas(config.personas_file),
        lines=_load_lines(config.lines_file),
        phase_prompts=_load_prompts(config.prompts_dir),
    )


def _load_personas(path: Path) -> Mapping[str, Persona]:
    raw = _section(read_yaml(path), "personas", path)
    personas: dict[str, Persona] = {}
    for persona_id, fields in raw.items():
        if not isinstance(fields, Mapping):
            raise ConfigError(f"Persona {persona_id!r} in {path} must be a mapping")
        try:
            personas[str(persona_id)] = Persona.model_validate({"id": persona_id, **fields})
        except ValidationError as exc:
            raise ConfigError(f"Invalid persona {persona_id!r} in {path}:\n{exc}") from exc
    return MappingProxyType(personas)


def _load_lines(path: Path) -> Mapping[str, Mapping[str, str]]:
    raw = _section(read_yaml(path), "lines", path)
    lines: dict[str, Mapping[str, str]] = {}
    for line_id, variants in raw.items():
        if not isinstance(variants, Mapping) or not isinstance(variants.get(DEFAULT_VARIANT), str):
            raise ConfigError(f"Line {line_id!r} in {path} needs a '{DEFAULT_VARIANT}' text")
        lines[str(line_id)] = MappingProxyType({str(k): str(v) for k, v in variants.items()})
    return MappingProxyType(lines)


def _load_prompts(folder: Path) -> Mapping[str, str]:
    if not folder.is_dir():
        raise ConfigError(f"Prompt folder not found: {folder}")
    prompts = {
        file.stem.upper(): file.read_text(encoding="utf-8").strip()
        for file in sorted(folder.glob("*.txt"))
    }
    return MappingProxyType(prompts)


def _section(data: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    section = data.get(key)
    if not isinstance(section, Mapping) or not section:
        raise ConfigError(f"{path} must contain a non-empty '{key}:' mapping")
    return section
