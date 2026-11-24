"""``config/alpha_mini.yaml``: the real Alpha Mini's moves, built only from verified RidK calls.

A move is a list of steps; a step is a built-in behavior (``rom.optional.behavior.play``) or a
list of keyframes (``rom.actuator.motor.write``). The file lists which joints (with a safe
range) and behaviors are ``verified`` — taken from the course's example scripts — and every
move is checked against that list at startup: an unverified joint or behavior, or a value
outside the range, is a ConfigError. RidK names are never guessed (see the file's header).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pipi_brain.config import ConfigError, read_yaml

BEHAVIOR_URI = "rom.optional.behavior.play"
MOTOR_URI = "rom.actuator.motor.write"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Keyframe(_Model):
    time: int = Field(gt=0)  # ms from the start of the step
    data: dict[str, float] = Field(min_length=1)  # joint -> radians


class MoveStep(_Model):
    behavior: str | None = Field(default=None, min_length=1)
    frames: tuple[Keyframe, ...] | None = Field(default=None, min_length=1)
    min_ms: int = Field(default=0, ge=0)  # wait at least this long before the next step

    @model_validator(mode="after")
    def _one_kind(self) -> MoveStep:
        if (self.behavior is None) == (self.frames is None):
            raise ValueError("a step needs exactly one of 'behavior' or 'frames'")
        if self.frames is not None:
            times = [frame.time for frame in self.frames]
            if times != sorted(set(times)):
                raise ValueError(f"keyframe times must increase: {times}")
        return self

    @property
    def duration_s(self) -> float:
        """The least time this step takes (frames: the last keyframe; behavior: ``min_ms``)."""
        last_ms = self.frames[-1].time if self.frames else 0
        return max(last_ms, self.min_ms) / 1000

    def call(self) -> tuple[str, dict[str, Any]]:
        """The RidK call for this step, exactly in the course examples' form."""
        if self.behavior is not None:
            return BEHAVIOR_URI, {"name": self.behavior}
        frames = [{"time": f.time, "data": dict(f.data)} for f in self.frames or ()]
        return MOTOR_URI, {"frames": frames, "force": True}


class Verified(_Model):
    joints: dict[str, tuple[float, float]] = Field(min_length=1)  # joint -> (min, max) radians
    behaviors: tuple[str, ...] = ()


class MovesFile(_Model):
    verified: Verified
    moves: dict[str, tuple[MoveStep, ...]] = Field(min_length=1)


class MoveLibrary:
    def __init__(self, moves: Mapping[str, tuple[MoveStep, ...]]) -> None:
        self._moves = MappingProxyType(dict(moves))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._moves)

    def get(self, name: str) -> tuple[MoveStep, ...] | None:
        return self._moves.get(name)

    def missing(self, names: Iterable[str]) -> list[str]:
        return sorted({name for name in names if name not in self._moves})


def check_verified(parsed: MovesFile) -> list[str]:
    """Every problem with unverified joints / behaviors or out-of-range values (empty = ok)."""
    problems: list[str] = []
    allowed_behaviors = set(parsed.verified.behaviors)
    for joint, (low, high) in parsed.verified.joints.items():
        if low > high:
            problems.append(f"verified range for {joint} is empty: [{low}, {high}]")
    for name, steps in parsed.moves.items():
        for index, step in enumerate(steps, start=1):
            where = f"move {name!r} step {index}"
            if step.behavior is not None and step.behavior not in allowed_behaviors:
                problems.append(f"{where}: behavior {step.behavior!r} is not verified")
            for frame in step.frames or ():
                for joint, value in frame.data.items():
                    limits = parsed.verified.joints.get(joint)
                    if limits is None:
                        problems.append(f"{where}: joint {joint!r} is not verified")
                    elif not limits[0] <= value <= limits[1]:
                        problems.append(
                            f"{where}: {joint}={value} is outside the verified range "
                            f"[{limits[0]}, {limits[1]}]"
                        )
    return problems


def load_moves(path: Path) -> MoveLibrary:
    """Read and validate alpha_mini.yaml. Raises ConfigError with a readable message."""
    raw = read_yaml(path)
    try:
        parsed = MovesFile.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid Alpha Mini moves in {path}:\n{exc}") from exc
    problems = check_verified(parsed)
    if problems:
        raise ConfigError(
            f"Alpha Mini moves in {path} use unverified RidK names or values "
            "(test them in the lab first):\n  - " + "\n  - ".join(problems)
        )
    return MoveLibrary(parsed.moves)
