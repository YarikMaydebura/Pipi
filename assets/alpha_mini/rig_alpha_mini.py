"""Rig the Alpha Mini look-alike with the same bone names and axes as Pipi (minus the antenna).

Same names = the same animation helpers and the same app code work for both bodies; Pipi's
signature_wave (shoulder.R + elbow.R only) plays identically on the robot. Every part is rigid
on one bone (the real robot is made of rigid shells driven by servos).

Run after build_alpha_mini.py (opens and re-saves out/alpha_mini.blend):
    "$BLENDER_PATH" --background --python assets/alpha_mini/rig_alpha_mini.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
PIPI3D = HERE.parent / "pipi3d"
if str(PIPI3D) not in sys.path:
    sys.path.insert(0, str(PIPI3D))

from rig import BoneSpec, bind, clear_old_rig, weight_rigid  # noqa: E402  (Pipi's rig helpers)

BLEND_PATH = HERE / "out" / "alpha_mini.blend"
RIG_NAME = "AlphaMiniRig"


def bone_specs(j: dict[str, list[float]]) -> list[BoneSpec]:
    hip_z = j["hip.L"][2]
    neck = tuple(j["neck"])
    specs = [
        BoneSpec("root", (0.0, 0.0, 0.0), (0.0, 0.0, 0.025), None),
        BoneSpec("hips", (0.0, 0.0, hip_z - 0.01), (0.0, 0.0, hip_z + 0.012), "root"),
        BoneSpec("spine", (0.0, 0.0, hip_z + 0.012), neck, "hips"),
        BoneSpec("head", neck, (neck[0], neck[1], neck[2] + 0.07), "spine"),
    ]
    for s in ("L", "R"):
        specs += [
            BoneSpec(f"shoulder.{s}", tuple(j[f"shoulder.{s}"]), tuple(j[f"elbow.{s}"]), "spine"),
            BoneSpec(f"elbow.{s}", tuple(j[f"elbow.{s}"]), tuple(j[f"wrist.{s}"]), f"shoulder.{s}"),
            BoneSpec(f"hand.{s}", tuple(j[f"wrist.{s}"]), tuple(j[f"hand_tip.{s}"]), f"elbow.{s}"),
            BoneSpec(f"thigh.{s}", tuple(j[f"hip.{s}"]), tuple(j[f"knee.{s}"]), "hips"),
            BoneSpec(f"shin.{s}", tuple(j[f"knee.{s}"]), tuple(j[f"ankle.{s}"]), f"thigh.{s}"),
            BoneSpec(f"foot.{s}", tuple(j[f"ankle.{s}"]), tuple(j[f"toe.{s}"]), f"shin.{s}"),
        ]
    return specs


def build_armature(specs: list[BoneSpec]) -> bpy.types.Object:
    data = bpy.data.armatures.new(RIG_NAME)
    rig = bpy.data.objects.new(RIG_NAME, data)
    bpy.context.scene.collection.objects.link(rig)
    data.display_type = "STICK"
    rig.show_in_front = True
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for spec in specs:
        bone = data.edit_bones.new(spec.name)
        bone.head, bone.tail = spec.head, spec.tail
        # same axis convention as Pipi's rig.py: Z backward (+Y), or up for bones along Y
        along_y = abs((Vector(spec.tail) - Vector(spec.head)).normalized().y) > 0.9
        bone.align_roll(Vector((0, 0, 1)) if along_y else Vector((0, 1, 0)))
        if spec.parent:
            bone.parent = data.edit_bones[spec.parent]
            bone.use_connect = (Vector(bone.head) - Vector(bone.parent.tail)).length < 1e-6
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def main() -> None:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))
    old = bpy.data.objects.get(RIG_NAME)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    clear_old_rig()
    joints = json.loads(bpy.context.scene["am_joints"])
    rig = build_armature(bone_specs(joints))
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    unassigned = [o.name for o in parts if "am_bone" not in o]
    if unassigned:
        raise RuntimeError(f"no bone recorded for: {unassigned}")
    for obj in parts:
        weight_rigid(obj, obj["am_bone"])
        bind(obj, rig)
    print(f"[alpha_mini] rig '{RIG_NAME}': {len(rig.data.bones)} bones, {len(parts)} parts bound")
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))


if __name__ == "__main__":
    main()
