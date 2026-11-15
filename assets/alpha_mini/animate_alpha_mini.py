"""Create the Alpha Mini look-alike's animation clips (named actions on AlphaMiniRig).

Clips: idle, talk, listen, think, nod, shake_head, signature_wave, dance, sleep (shared with
Pipi, same data, so both bodies move alike) and robot versions of happy, celebrate and
wake_up (a rigid robot does not squash, stretch or hop). 24 fps. Conventions: see
assets/pipi3d/animate.py.

Run after rig_alpha_mini.py (opens and re-saves out/alpha_mini.blend):
    "$BLENDER_PATH" --background --python assets/alpha_mini/animate_alpha_mini.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
PIPI3D = HERE.parent / "pipi3d"
if str(PIPI3D) not in sys.path:
    sys.path.insert(0, str(PIPI3D))

import clips_core  # noqa: E402
import clips_cute  # noqa: E402
from animate import FPS, bake_clip, reset_rig_animation, validate  # noqa: E402
from clip_types import Clip, Pose, arms, merge, rest  # noqa: E402

BLEND_PATH = HERE / "out" / "alpha_mini.blend"
RIG_NAME = "AlphaMiniRig"
NOT_ON_ROBOT = {"antenna_base", "antenna_tip"}
_ARMS = ("shoulder.R", "shoulder.L", "elbow.R", "elbow.L")


def for_robot(clip: Clip) -> Clip:
    """Pipi's clip without the bones the robot does not have."""
    keys = {frame: {bone: ch for bone, ch in pose.items() if bone not in NOT_ON_ROBOT}
            for frame, pose in clip.keys.items()}
    return Clip(clip.name, clip.length, clip.loop, keys)


SHARED = [clips_core.IDLE, clips_core.TALK, clips_core.THINK, clips_core.SIGNATURE_WAVE,
          clips_core.SLEEP, clips_cute.LISTEN, clips_cute.NOD, clips_cute.SHAKE_HEAD, clips_cute.DANCE]

_SLUMP: Pose = merge({"spine": {"rot": (-12, 0, 2)}, "head": {"rot": (-18, 0, 10)}},
                     arms((-12, 0, -3), elbow_r=(-10, 0, 0)))

HAPPY = Clip("happy", 24, False, {
    0: rest("spine", "head", *_ARMS),
    6: merge(arms((0, 0, 85), elbow_r=(0, 0, 35)), {"head": {"rot": (8, 0, 0)}, "spine": {"rot": (3, 0, 0)}}),
    10: {"spine": {"rot": (3, 0, 4)}, "head": {"rot": (8, 0, 6)}},
    14: {"spine": {"rot": (3, 0, -4)}, "head": {"rot": (8, 0, -6)}},
    18: merge(arms((0, 0, 80), elbow_r=(0, 0, 30)), {"spine": {"rot": (2, 0, 0)}, "head": {"rot": (5, 0, 0)}}),
    24: rest("spine", "head", *_ARMS),
})

CELEBRATE = Clip("celebrate", 36, False, {
    0: rest("spine", "head", *_ARMS),
    6: merge(arms((0, 0, 95), elbow_r=(0, 0, 25)), {"head": {"rot": (8, 0, 0)}}),
    **{f: merge(arms(r=(0, 0, 95 + 12 * d), l=(0, 0, -(95 - 12 * d)),
                     elbow_r=(0, 0, 25 + 20 * d), elbow_l=(0, 0, -(25 - 20 * d))),
                {"spine": {"rot": (0, 0, 4 * d)}, "head": {"rot": (8, 0, 5 * d)}})
       for f, d in {11: 1, 16: -1, 21: 1, 26: -1}.items()},
    31: merge(arms((0, 0, 60), elbow_r=(0, 0, 15)), {"spine": {"rot": (0, 0, 0)}, "head": {"rot": (4, 0, 0)}}),
    36: rest("spine", "head", *_ARMS),
})

WAKE_UP = Clip("wake_up", 40, False, {  # from the sleep slump: head up, look around, stretch
    0: _SLUMP,
    8: {"spine": {"rot": (-4, 0, 0)}, "head": {"rot": (-4, 0, 4)}},
    14: {"spine": {"rot": (0, 0, 0)}, "head": {"rot": (4, 22, 0)}},
    20: {"head": {"rot": (4, -22, 0)}},
    26: merge({"head": {"rot": (6, 0, 0)}}, arms((-10, 0, 38), elbow_r=(0, 0, 55))),
    32: merge({"head": {"rot": (3, 0, 0)}}, arms((-5, 0, 20), elbow_r=(0, 0, 20))),
    40: rest("spine", "head", *_ARMS),
})

CLIPS = [for_robot(c) for c in SHARED] + [HAPPY, CELEBRATE, WAKE_UP]


def main() -> None:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))
    scene = bpy.context.scene
    scene.render.fps = FPS
    rig = bpy.data.objects.get(RIG_NAME)
    if rig is None:
        raise RuntimeError("AlphaMiniRig not found: run rig_alpha_mini.py first")
    validate(CLIPS, rig)
    reset_rig_animation(rig)
    for clip in CLIPS:
        bake_clip(rig, clip)
    scene.frame_start, scene.frame_end = 1, max(c.length for c in CLIPS) + 1
    print(f"[alpha_mini] {len(CLIPS)} clips: " + ", ".join(c.name for c in CLIPS))
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))


if __name__ == "__main__":
    main()
