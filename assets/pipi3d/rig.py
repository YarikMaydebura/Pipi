"""Add Pipi's armature and bind the model to it.

Run after build_pipi.py (it opens and re-saves out/pipi.blend; safe to run again):
    macOS:    "$BLENDER_PATH" --background --python assets/pipi3d/rig.py
    Windows:  & $env:BLENDER_PATH --background --python assets/pipi3d/rig.py

Bones: root, hips, spine, head, antenna_base, antenna_tip, shoulder.L/R, elbow.L/R, hand.L/R,
thigh.L/R, shin.L/R, foot.L/R. No IK.

Weights are computed here instead of Blender's automatic (heat) weights: Pipi is made of
separate, overlapping shells, where heat weighting bleeds between parts (body following the
head) or fails. Rigid parts get 100% on one bone, like a vinyl toy; the bendy parts (arms,
legs, antenna) get a smooth two-bone blend so elbows, knees and the antenna bend softly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
BLEND_PATH = HERE / "out" / "pipi.blend"
RIG_NAME = "PipiRig"


@dataclass(frozen=True)
class BoneSpec:
    name: str
    head: tuple[float, float, float]
    tail: tuple[float, float, float]
    parent: str | None


def mirrored(name: str, head: tuple[float, float, float], tail: tuple[float, float, float],
             parent: str) -> list[BoneSpec]:
    """Left (+X) and right (-X) copies; '{s}' in names becomes L / R."""
    out = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        p = parent.format(s=side)
        out.append(BoneSpec(name.format(s=side), (sign * head[0], head[1], head[2]),
                            (sign * tail[0], tail[1], tail[2]), p))
    return out


# Joint positions match build_pipi.py (metres, Z up, Pipi faces -Y).
SHOULDER = (0.045, 0.0, 0.117)
ELBOW = (0.055, -0.001, 0.098)
WRIST = (0.062, -0.002, 0.082)
HIP = (0.022, 0.0, 0.058)
KNEE = (0.022, 0.0, 0.039)
ANKLE = (0.022, 0.0, 0.020)

BONES: list[BoneSpec] = [
    BoneSpec("root", (0.0, 0.0, 0.0), (0.0, 0.0, 0.03), None),
    BoneSpec("hips", (0.0, 0.0, 0.055), (0.0, 0.0, 0.085), "root"),
    BoneSpec("spine", (0.0, 0.0, 0.085), (0.0, 0.0, 0.130), "hips"),
    BoneSpec("head", (0.0, 0.0, 0.130), (0.0, 0.0, 0.262), "spine"),
    BoneSpec("antenna_base", (0.0, 0.002, 0.262), (0.001, 0.002, 0.276), "head"),
    BoneSpec("antenna_tip", (0.001, 0.002, 0.276), (0.004, 0.001, 0.289), "antenna_base"),
    *mirrored("shoulder.{s}", SHOULDER, ELBOW, "spine"),
    *mirrored("elbow.{s}", ELBOW, WRIST, "shoulder.{s}"),
    *mirrored("hand.{s}", WRIST, (0.064, -0.002, 0.064), "elbow.{s}"),
    *mirrored("thigh.{s}", HIP, KNEE, "hips"),
    *mirrored("shin.{s}", KNEE, ANKLE, "thigh.{s}"),
    *mirrored("foot.{s}", (0.025, -0.004, 0.020), (0.025, -0.030, 0.010), "shin.{s}"),
]

# Rigid parts: object name -> bone ({s} = L/R).
RIGID: dict[str, str] = {
    "Body": "spine", "BellyPanel": "spine", "ChestLight": "spine",
    "Head": "head", "FaceScreen": "head", "Mouth": "head", "AntennaBase": "head",
    "Sprout": "antenna_tip",
    "Eye{s}": "head", "Cheek{s}": "head",
    "Shoulder{s}": "shoulder.{s}", "Hand{s}": "hand.{s}", "Foot{s}": "foot.{s}",
}
# Bendy parts: object -> (first bone, second bone, segment start, segment end) for the blend.
BLENDED: dict[str, tuple[str, str, tuple, tuple]] = {
    "Arm{s}": ("shoulder.{s}", "elbow.{s}", SHOULDER, WRIST),
    "Leg{s}": ("thigh.{s}", "shin.{s}", HIP, ANKLE),
    "Antenna": ("antenna_base", "antenna_tip", (0.0, 0.002, 0.262), (0.004, 0.001, 0.289)),
}
BLEND_START, BLEND_END = 0.35, 0.65  # blend zone around the joint, as fraction of the segment


def expand(table: dict) -> dict:
    """Replace '{s}' with L and R (with the matching sign for positions)."""
    out = {}
    for key, value in table.items():
        if "{s}" not in key:
            out[key] = value
            continue
        for side, sign in (("L", 1.0), ("R", -1.0)):
            if isinstance(value, str):
                out[key.format(s=side)] = value.format(s=side)
            else:
                a, b, p0, p1 = value
                flip = lambda p, sg=sign: (sg * p[0], p[1], p[2])  # noqa: E731
                out[key.format(s=side)] = (a.format(s=side), b.format(s=side), flip(p0), flip(p1))
    return out


def clear_old_rig() -> None:
    old = bpy.data.objects.get(RIG_NAME)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        for mod in [m for m in obj.modifiers if m.type == "ARMATURE"]:
            obj.modifiers.remove(mod)
        obj.vertex_groups.clear()


def build_armature() -> bpy.types.Object:
    data = bpy.data.armatures.new(RIG_NAME)
    rig = bpy.data.objects.new(RIG_NAME, data)
    bpy.context.scene.collection.objects.link(rig)
    data.display_type = "STICK"
    rig.show_in_front = True
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for spec in BONES:
        bone = data.edit_bones.new(spec.name)
        bone.head, bone.tail = spec.head, spec.tail
        # Clean axes: local Z points backward (+Y) so "rotate around Z" = swing in the front
        # plane (sideways) and "around X" = swing forward/back. Bones that run along Y (feet)
        # point their Z up instead.
        along_y = abs((Vector(spec.tail) - Vector(spec.head)).normalized().y) > 0.9
        bone.align_roll(Vector((0, 0, 1)) if along_y else Vector((0, 1, 0)))
        if spec.parent:
            bone.parent = data.edit_bones[spec.parent]
            bone.use_connect = Vector(bone.head) == Vector(bone.parent.tail)
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def smoothstep(e0: float, e1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def bind(obj: bpy.types.Object, rig: bpy.types.Object) -> None:
    world = obj.matrix_world.copy()
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()
    obj.matrix_world = world
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = rig


def weight_rigid(obj: bpy.types.Object, bone: str) -> None:
    group = obj.vertex_groups.new(name=bone)
    group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")


def weight_blended(obj: bpy.types.Object, first: str, second: str, p0: tuple, p1: tuple) -> None:
    g1, g2 = obj.vertex_groups.new(name=first), obj.vertex_groups.new(name=second)
    a, b = Vector(p0), Vector(p1)
    seg = b - a
    for v in obj.data.vertices:
        w = obj.matrix_world @ v.co
        t = (w - a).dot(seg) / seg.length_squared
        k = smoothstep(BLEND_START, BLEND_END, t)
        g1.add([v.index], 1.0 - k, "REPLACE")
        g2.add([v.index], k, "REPLACE")


def main() -> None:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))
    clear_old_rig()
    rig = build_armature()
    rigid, blended = expand(RIGID), expand(BLENDED)
    missing = []
    for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        if obj.name in rigid:
            weight_rigid(obj, rigid[obj.name])
        elif obj.name in blended:
            weight_blended(obj, *blended[obj.name])
        else:
            missing.append(obj.name)
            continue
        bind(obj, rig)
    if missing:
        raise RuntimeError(f"no bone assigned for: {missing}")  # every part must follow the rig
    print(f"[pipi] rig '{RIG_NAME}': {len(BONES)} bones, {len(rigid) + len(blended)} parts bound")
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    print(f"[pipi] saved {BLEND_PATH}")


if __name__ == "__main__":
    main()
