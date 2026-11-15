"""Small data types + helpers for writing Pipi's animation clips as plain data (no bpy).

A clip is a dict of frame -> {bone: {"rot": (x, y, z) degrees, "loc": (x, y, z) m,
"scale": (x, y, z)}}. Frames are 0-based; animate.py shifts them to start at 1.
See animate.py for the rotation conventions.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

Channels = dict[str, tuple[float, float, float]]
Pose = dict[str, Channels]

REST: Channels = {"rot": (0.0, 0.0, 0.0)}
REST_ROOT: Channels = {"loc": (0.0, 0.0, 0.0), "rot": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0)}


@dataclass(frozen=True)
class Clip:
    name: str
    length: int  # frames at 24 fps
    loop: bool
    keys: dict[int, Pose] = field(default_factory=dict)


def arms(r: tuple[float, float, float], l: tuple[float, float, float] | None = None,
         elbow_r: tuple[float, float, float] | None = None,
         elbow_l: tuple[float, float, float] | None = None) -> Pose:
    """Arm pose; the left side mirrors the right unless given (Y and Z flip sign)."""
    def mirror(v: tuple[float, float, float]) -> tuple[float, float, float]:
        return (v[0], -v[1], -v[2])
    pose: Pose = {"shoulder.R": {"rot": r}, "shoulder.L": {"rot": l if l is not None else mirror(r)}}
    if elbow_r is not None:
        pose["elbow.R"] = {"rot": elbow_r}
        pose["elbow.L"] = {"rot": elbow_l if elbow_l is not None else mirror(elbow_r)}
    return pose


def merge(*poses: Pose) -> Pose:
    out: Pose = {}
    for pose in poses:
        for bone, ch in pose.items():
            out[bone] = {**out.get(bone, {}), **ch}
    return out


def rest(*bones: str) -> Pose:
    return {b: dict(REST_ROOT if b == "root" else REST) for b in bones}


def wave(length: int, step: int, fn: Callable[[float], Pose]) -> dict[int, Pose]:
    """Sample fn(phase 0..1) every `step` frames over a loop; last key equals the first."""
    keys = {f: fn(f / length) for f in range(0, length, step)}
    keys[length] = fn(0.0)
    return keys


def sin01(phase: float, cycles: float = 1.0, offset: float = 0.0) -> float:
    return math.sin(2 * math.pi * (phase * cycles + offset))


ALL_POSABLE = (
    "root", "hips", "spine", "head", "antenna_base", "antenna_tip",
    "shoulder.L", "shoulder.R", "elbow.L", "elbow.R", "hand.L", "hand.R",
    "thigh.L", "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R",
)
