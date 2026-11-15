"""Export Pipi to binary glTF (out/pipi.glb) and verify the result.

Run after animate.py:
    macOS:    "$BLENDER_PATH" --background --python assets/pipi3d/export.py
    Windows:  & $env:BLENDER_PATH --background --python assets/pipi3d/export.py

The glb holds the skinned model, every animation clip (one glTF animation per action),
glTF PBR materials with emission kept, and the eye/mouth images. After exporting, the file is
read back and checked against the contract the desktop pet relies on (names, clips, size,
triangle budget); any problem stops the script with a clear error.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import clips_core  # noqa: E402
import clips_cute  # noqa: E402

BLEND_PATH = HERE / "out" / "pipi.blend"
GLB_PATH = HERE / "out" / "pipi.glb"

MAX_BYTES = 5 * 1024 * 1024
MAX_TRIANGLES = 20_000
REQUIRED_NODES = {"EyeL", "EyeR", "Mouth", "CheekL", "CheekR", "ChestLight", "Sprout", "Head", "Body"}
REQUIRED_MATERIALS = {"EyeScreen", "MouthScreen", "Cheek", "ChestLight", "Sprout", "FaceScreen"}
REQUIRED_BONES = {
    "root", "hips", "spine", "head", "antenna_base", "antenna_tip",
    *(f"{b}.{s}" for b in ("shoulder", "elbow", "hand", "thigh", "shin", "foot") for s in ("L", "R")),
}

EXPORT_OPTIONS = {
    "export_format": "GLB",
    "export_yup": True,
    "export_apply": True,  # bake modifiers (e.g. the face screen thickness); armature stays a skin
    "export_skins": True,
    "export_animations": True,
    "export_animation_mode": "ACTIONS",  # one glTF animation per clip
    "export_anim_slide_to_zero": True,
    "export_force_sampling": True,
    "export_optimize_animation_size": True,
    "export_leaf_bone": False,
    "export_def_bones": False,
    "export_materials": "EXPORT",
    "export_image_format": "AUTO",
    "export_extras": False,
    "export_unused_images": False,
}


def export() -> None:
    supported = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    options = {k: v for k, v in EXPORT_OPTIONS.items() if k in supported}
    skipped = sorted(set(EXPORT_OPTIONS) - supported)
    if skipped:
        print(f"[pipi] note: this Blender's glTF exporter has no option(s) {skipped}; using defaults")
    bpy.ops.export_scene.gltf(filepath=str(GLB_PATH), **options)


def read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, _length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise ValueError(f"{path} is not a glTF 2.0 binary file")
    chunk_len, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        raise ValueError("first glb chunk is not JSON")
    return json.loads(data[20:20 + chunk_len])


def count_triangles(gltf: dict) -> int:
    total = 0
    for mesh in gltf.get("meshes", []):
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                continue
            accessor = prim.get("indices", prim["attributes"]["POSITION"])
            total += gltf["accessors"][accessor]["count"] // 3
    return total


def verify(path: Path) -> list[str]:
    gltf = read_glb_json(path)
    problems = []
    size = path.stat().st_size
    if size > MAX_BYTES:
        problems.append(f"file is {size / 1e6:.2f} MB (limit {MAX_BYTES / 1e6:.0f} MB)")
    tris = count_triangles(gltf)
    if tris > MAX_TRIANGLES:
        problems.append(f"{tris} triangles (limit {MAX_TRIANGLES})")
    nodes = {n.get("name", "") for n in gltf.get("nodes", [])}
    mats = {m.get("name", "") for m in gltf.get("materials", [])}
    anims = {a.get("name", "") for a in gltf.get("animations", [])}
    expected_clips = {c.name for c in clips_core.CLIPS + clips_cute.CLIPS}
    for label, need, have in (("nodes", REQUIRED_NODES, nodes), ("bones", REQUIRED_BONES, nodes),
                              ("materials", REQUIRED_MATERIALS, mats), ("clips", expected_clips, anims)):
        missing = sorted(need - have)
        if missing:
            problems.append(f"missing {label}: {missing}")
    if not gltf.get("skins"):
        problems.append("no skin (armature) exported")
    eye = next((m for m in gltf.get("materials", []) if m.get("name") == "EyeScreen"), {})
    if eye.get("alphaMode") != "BLEND":
        problems.append(f"EyeScreen alphaMode is {eye.get('alphaMode', 'OPAQUE')}, expected BLEND")
    print(f"[pipi] glb: {size / 1e6:.2f} MB, {tris} triangles, {len(anims)} clips, "
          f"{len(gltf.get('materials', []))} materials, {len(gltf.get('images', []))} images")
    return problems


def main() -> None:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))
    if bpy.data.objects.get("PipiRig") is None:
        raise RuntimeError("PipiRig not found: run rig.py and animate.py first")
    export()
    problems = verify(GLB_PATH)
    if problems:
        raise RuntimeError("glb check failed:\n  - " + "\n  - ".join(problems))
    print(f"[pipi] exported and verified {GLB_PATH}")


if __name__ == "__main__":
    main()
