"""Build the Alpha Mini look-alike used by the fake robot (the physical robot's stand-in).

The shapes come from the part scripts in parts/ (written while modelling the robot from
reference photos in a live Blender session; same shapes, only the mesh density was lowered
for real-time use). This script runs them, gives the robot Pipi's eyes (the identity cue:
same Pipi, other body), records which bone every part belongs to, lightens the meshes, bakes
everything to real size (0.245 m, Z up, facing -Y, origin between the feet) and saves
out/alpha_mini.blend.

Run (Blender 4.2+, headless), then rig_alpha_mini.py, animate_alpha_mini.py, export_alpha_mini.py:
    macOS:    "$BLENDER_PATH" --background --python assets/alpha_mini/build_alpha_mini.py
    Windows:  & $env:BLENDER_PATH --background --python assets/alpha_mini/build_alpha_mini.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
PIPI3D = HERE.parent / "pipi3d"
for path in (HERE, PIPI3D):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import eye_images  # noqa: E402  (Pipi's eye drawer, reused for the robot's eye displays)

OUT_DIR = HERE / "out"
BLEND_PATH = OUT_DIR / "alpha_mini.blend"
PARTS = ["am_helpers.py", "am_body.py", "am_head.py", "am_arms.py", "am_badge.py"]
TARGET_HEIGHT = 0.245  # the real Alpha Mini is about 24.5 cm tall
EYE_BACKGROUND = (0.03, 0.05, 0.06)  # dark round display behind Pipi's teal eye

# Final material values chosen while modelling (linear RGB, roughness, metallic, coat).
MATERIALS = {
    "PipiWhite": ((0.86, 0.855, 0.83), 0.28, 0.0, 0.35),
    "PipiGrey": ((0.30, 0.295, 0.29), 0.42, 0.0, 0.20),
    "PipiGreyLight": ((0.50, 0.495, 0.48), 0.36, 0.0, 0.20),
    "PipiSilver": ((0.70, 0.70, 0.71), 0.25, 0.75, 0.0),
    "PipiDark": ((0.05, 0.05, 0.055), 0.18, 0.0, 0.0),
    "PipiDarkGrey": ((0.10, 0.10, 0.105), 0.35, 0.0, 0.0),
    "PipiBlueGlow": ((0.15, 0.45, 0.95), 0.30, 0.0, 0.0),
}

# Part name -> bone. Arms/head/hands follow the empties they hang from; legs and torso by name.
LEG_PARTS = {"Thigh": "thigh", "KneePad": "thigh", "Knee": "shin", "Shin": "shin", "Ankle": "shin",
             "Foot": "foot", "Sole": "foot"}
HIPS_PARTS = {"Pelvis"}
EMPTY_TO_BONE = {"Head": "head", "Hand": "hand", "Elbow": "elbow", "Arm": "shoulder"}


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def load_part_texts() -> None:
    for name in PARTS:
        text = bpy.data.texts.new(name)
        text.write((HERE / "parts" / name).read_text(encoding="utf-8"))


def part_namespace(name: str) -> dict:
    """The part scripts were written for Blender's live console, where bpy is preloaded."""
    import bmesh
    import math

    return {"__name__": f"alpha_mini_{name}", "bpy": bpy, "bmesh": bmesh, "math": math,
            "Vector": Vector, "Matrix": Matrix}


def run_part(name: str) -> None:
    exec(bpy.data.texts[name].as_string(), part_namespace(name))  # noqa: S102


def make_materials() -> None:
    namespace = part_namespace("am_helpers.py")
    exec(bpy.data.texts["am_helpers.py"].as_string(), namespace)  # noqa: S102
    for name, (color, rough, metal, coat) in MATERIALS.items():
        namespace["make_mat"](name, color, rough=rough, metal=metal, coat=coat)
    glow = bpy.data.materials["PipiBlueGlow"]
    bsdf = next(n for n in glow.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Emission Color"].default_value = (0.2, 0.5, 1.0, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 3.0
    make_eye_material()


def pipi_eye_image() -> bpy.types.Image:
    """Pipi's idle eye on a dark round display (canvas rows are top-down; Blender bottom-up)."""
    rgba = eye_images.render_state(eye_images.STATES["idle"])
    alpha = rgba[..., 3:4]
    rgb = rgba[..., :3] * alpha + np.array(EYE_BACKGROUND, np.float32) * (1 - alpha)
    pixels = np.concatenate([rgb, np.ones_like(alpha)], axis=-1)[::-1]
    image = bpy.data.images.new("AlphaMiniEyes", eye_images.SIZE, eye_images.SIZE, alpha=False)
    image.pixels.foreach_set(np.ascontiguousarray(pixels, np.float32).ravel())
    image.pack()
    return image


def make_eye_material() -> None:
    mat = bpy.data.materials.new("EyeScreen")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = pipi_eye_image()
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.05
    bsdf.inputs["Coat Weight"].default_value = 1.0
    mat.diffuse_color = (*EYE_BACKGROUND, 1.0)


def side_of(name: str) -> str:
    return "L" if name.endswith("L") else "R"


def bone_for(obj: bpy.types.Object) -> str:
    """Which bone a part follows (rigid), from its name or the empty it hangs from."""
    base = obj.name.rstrip("LR")
    if obj.name[-1:] in "LR" and base in LEG_PARTS:
        return f"{LEG_PARTS[base]}.{side_of(obj.name)}"
    if obj.name in HIPS_PARTS:
        return "hips"
    node = obj.parent
    while node is not None:
        stem = node.name.rstrip("LR")
        if stem in EMPTY_TO_BONE:
            bone = EMPTY_TO_BONE[stem]
            return bone if bone == "head" else f"{bone}.{side_of(node.name)}"
        node = node.parent
    return "spine"  # torso, neck, badge


def joint_positions() -> dict[str, list[float]]:
    """World positions of the joints (before scaling), read from the build's pivot empties."""
    obj = bpy.data.objects
    joints = {"neck": list(obj["Head"].matrix_world.translation)}
    for s in ("L", "R"):
        joints[f"shoulder.{s}"] = list(obj[f"Arm{s}"].matrix_world.translation)
        joints[f"elbow.{s}"] = list(obj[f"Elbow{s}"].matrix_world.translation)
        joints[f"wrist.{s}"] = list(obj[f"Hand{s}"].matrix_world.translation)
        palm = obj[f"Palm{s}"].matrix_world.translation
        joints[f"hand_tip.{s}"] = [palm.x, palm.y, palm.z - 0.10]
        hip = obj[f"Leg{s}"].matrix_world.translation
        joints[f"hip.{s}"] = list(hip)
        joints[f"knee.{s}"] = [hip.x, obj[f"Knee{s}"].matrix_world.translation.y, obj[f"Knee{s}"].matrix_world.translation.z]
        ankle = obj[f"Ankle{s}"].matrix_world.translation
        joints[f"ankle.{s}"] = [hip.x, ankle.y, ankle.z]
        foot = obj[f"Foot{s}"].matrix_world.translation
        joints[f"toe.{s}"] = [foot.x, foot.y - 0.30, foot.z]
    return joints


def model_height() -> float:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    zs = []
    for o in bpy.context.scene.objects:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        zs.extend((ev.matrix_world @ v.co).z for v in mesh.vertices)
        ev.to_mesh_clear()
    return max(zs) - min(zs)


MAX_BEVEL_SEGMENTS = 3


def lighten_for_realtime() -> None:
    """The part scripts were tuned for renders; the web page needs far fewer triangles."""
    for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        for mod in list(obj.modifiers):
            if mod.type == "SUBSURF":
                obj.modifiers.remove(mod)
            elif mod.type == "BEVEL":
                mod.segments = min(mod.segments, MAX_BEVEL_SEGMENTS)


def bake_to_real_size(scale: float) -> None:
    """Move every part's world transform into its mesh, scale to real size, drop the empties."""
    for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        world = obj.matrix_world.copy()
        factor = world.to_scale().x * scale  # uniform: the head group is scaled 1.1
        obj.parent = None
        obj.data.transform(world)
        obj.data.transform(Matrix.Scale(scale, 4))
        obj.matrix_world = Matrix.Identity(4)
        for mod in obj.modifiers:
            if mod.type == "BEVEL":
                mod.width *= factor
            elif mod.type == "SOLIDIFY":
                mod.thickness *= factor
    for obj in [o for o in bpy.context.scene.objects if o.type == "EMPTY"]:
        bpy.data.objects.remove(obj, do_unlink=True)


def main() -> None:
    reset_scene()
    load_part_texts()
    make_materials()
    for name in PARTS[1:]:
        run_part(name)
    bpy.context.view_layer.update()
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj["am_bone"] = bone_for(obj)
    joints = joint_positions()
    lighten_for_realtime()
    scale = TARGET_HEIGHT / model_height()
    bake_to_real_size(scale)
    bpy.context.scene["am_joints"] = json.dumps({k: [c * scale for c in v] for k, v in joints.items()})
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    bones = sorted({o["am_bone"] for o in bpy.context.scene.objects if o.type == "MESH"})
    print(f"[alpha_mini] {sum(o.type == 'MESH' for o in bpy.context.scene.objects)} parts, "
          f"height {model_height():.4f} m, bones used: {bones}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    print(f"[alpha_mini] saved {BLEND_PATH}")


if __name__ == "__main__":
    main()
