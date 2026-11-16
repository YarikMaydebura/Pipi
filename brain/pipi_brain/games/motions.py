"""``config/motions.yaml``: canonical motion names -> what each body plays (docs/GAMES.md §2).

Games only use the canonical names. ``MotionLibrary.resolve(name, body)`` gives the name to
send in the ``motion`` message for that body, or None when the body cannot play it (the real
Alpha Mini until its RidK mapping is filled in after the lab test, M5).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pipi_brain.config import ConfigError, read_yaml

BODIES = ("fake_robot", "desktop_pet", "alpha_mini")


class MotionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    group: str = Field(min_length=1)
    fake_robot: str | None = Field(default=None, min_length=1)
    desktop_pet: str | None = Field(default=None, min_length=1)
    alpha_mini: str | None = Field(default=None, min_length=1)  # RidK: filled in M5


class MotionLibrary:
    def __init__(self, motions: Mapping[str, MotionEntry]) -> None:
        self._motions = MappingProxyType(dict(motions))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._motions)

    def known(self, name: str) -> bool:
        return name in self._motions

    def resolve(self, name: str, body: str | None) -> str | None:
        """What ``body`` plays for the canonical ``name``; None = it cannot play it."""
        entry = self._motions.get(name)
        if entry is None or body not in BODIES:
            return None
        value: str | None = getattr(entry, body)
        return value

    def supports(self, body: str | None, group: str | None = None) -> bool:
        """True if ``body`` can play at least one motion (of ``group``, if given)."""
        return any(
            self.resolve(name, body) is not None
            for name, entry in self._motions.items()
            if group is None or entry.group == group
        )

    def unknown(self, names: Iterable[str]) -> list[str]:
        return sorted({name for name in names if name not in self._motions})


def load_motions(path: Path) -> MotionLibrary:
    """Read and validate motions.yaml. Raises ConfigError with a readable message."""
    raw = read_yaml(path).get("motions")
    if not isinstance(raw, Mapping) or not raw:
        raise ConfigError(f"{path} must contain a non-empty 'motions:' mapping")
    motions: dict[str, MotionEntry] = {}
    for name, fields in raw.items():
        try:
            motions[str(name)] = MotionEntry.model_validate(fields)
        except ValidationError as exc:
            raise ConfigError(f"Invalid motion {name!r} in {path}:\n{exc}") from exc
    return MotionLibrary(motions)
