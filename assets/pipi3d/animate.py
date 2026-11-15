"""Create Pipi's animations as named actions on PipiRig (exported as glTF clips).

Run after rig.py (opens and re-saves out/pipi.blend; safe to run again):
    macOS:    "$BLENDER_PATH" --background --python assets/pipi3d/animate.py
    Windows:  & $env:BLENDER_PATH --background --python assets/pipi3d/animate.py

Clips are defined as data in clips_core.py (the 8 spec clips) and clips_cute.py (reactions for
interaction). Each clip becomes one action, stashed in its own muted NLA track so the glTF
exporter writes every clip as a separate animation. 24 fps.

Rotation conventions (degrees, local bone axes, set up by rig.py):
  arms   shoulder/elbow: Z = raise sideways (+ for .R, - for .L); X < 0 = swing forward
  legs   thigh: X < 0 = swing forward; shin: X > 0 = bend the knee
  head / spine / antenna: X > 0 = tilt back (look up), X < 0 = nod down;
         Z > 0 = lean toward Pipi's left (+X); Y > 0 = turn the face toward Pipi's left
  root   loc x < 0 = move to world +X; loc y = up; loc z > 0 = move backward;
         rot Y > 0 = turn to face +X; scale (x, y, z) with y = vertical (squash & stretch)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from clip_types import Clip  # noqa: E402
import clips_core  # noqa: E402
import clips_cute  # noqa: E402

BLEND_PATH = HERE / "out" / "pipi.blend"
RIG_NAME = "PipiRig"
FPS = 24


def reset_rig_animation(rig: bpy.types.Object) -> None:
    """Remove old clips so the script is idempotent."""
    if rig.animation_data:
        for track in list(rig.animation_data.nla_tracks):
            rig.animation_data.nla_tracks.remove(track)
        rig.animation_data.action = None
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)
    for bone in rig.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)


def key_channels(bone: bpy.types.PoseBone, channels: dict, frame: int) -> None:
    if "rot" in channels:
        bone.rotation_euler = tuple(math.radians(a) for a in channels["rot"])
        bone.keyframe_insert("rotation_euler", frame=frame)
    if "loc" in channels:
        bone.location = channels["loc"]
        bone.keyframe_insert("location", frame=frame)
    if "scale" in channels:
        bone.scale = channels["scale"]
        bone.keyframe_insert("scale", frame=frame)


def bake_clip(rig: bpy.types.Object, clip: Clip) -> bpy.types.Action:
    action = bpy.data.actions.new(clip.name)
    action.use_fake_user = True
    rig.animation_data_create()
    rig.animation_data.action = action
    for bone in rig.pose.bones:  # every clip starts from the rest pose
        bone.location, bone.rotation_euler, bone.scale = (0, 0, 0), (0, 0, 0), (1, 1, 1)
    for frame, pose in sorted(clip.keys.items()):
        for bone_name, channels in pose.items():
            key_channels(rig.pose.bones[bone_name], channels, frame + 1)
    action.frame_range = (1, clip.length + 1)
    action["pipi_loop"] = clip.loop  # read by export.py / documentation
    track = rig.animation_data.nla_tracks.new()
    track.name = clip.name
    track.strips.new(clip.name, 1, action)
    track.mute = True
    rig.animation_data.action = None
    return action


def validate(clips: list[Clip], rig: bpy.types.Object) -> None:
    names = [c.name for c in clips]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate clip names: {dupes}")
    bones = set(rig.pose.bones.keys())
    for clip in clips:
        for frame, pose in clip.keys.items():
            unknown = set(pose) - bones
            if unknown:
                raise ValueError(f"{clip.name} frame {frame}: unknown bones {unknown}")
            if not 0 <= frame <= clip.length:
                raise ValueError(f"{clip.name}: key at frame {frame} outside 0..{clip.length}")


def main() -> None:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))
    scene = bpy.context.scene
    scene.render.fps = FPS
    rig = bpy.data.objects.get(RIG_NAME)
    if rig is None:
        raise RuntimeError("PipiRig not found: run rig.py first")
    clips = clips_core.CLIPS + clips_cute.CLIPS
    validate(clips, rig)
    reset_rig_animation(rig)
    for clip in clips:
        bake_clip(rig, clip)
    scene.frame_start, scene.frame_end = 1, max(c.length for c in clips) + 1
    print(f"[pipi] {len(clips)} clips: " + ", ".join(f"{c.name}({c.length}f{' loop' if c.loop else ''})" for c in clips))
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    print(f"[pipi] saved {BLEND_PATH}")


if __name__ == "__main__":
    main()
