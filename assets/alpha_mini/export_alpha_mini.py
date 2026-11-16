"""Export the Alpha Mini look-alike to out/alpha_mini.glb, verify it, and (with --to-web)
copy it to web/public/models/alpha_mini.glb where the fake robot page loads it.

Run after animate_alpha_mini.py:
    "$BLENDER_PATH" --background --python assets/alpha_mini/export_alpha_mini.py -- --to-web
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PIPI3D = HERE.parent / "pipi3d"
for path in (HERE, PIPI3D):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from export import EXPORT_OPTIONS, count_triangles, read_glb_json  # noqa: E402

BLEND_PATH = HERE / "out" / "alpha_mini.blend"
GLB_PATH = HERE / "out" / "alpha_mini.glb"
WEB_PATH = REPO / "web" / "public" / "models" / "alpha_mini.glb"

MAX_BYTES = 4 * 1024 * 1024
MAX_TRIANGLES = 60_000
REQUIRED_NODES = {"EyeL", "EyeR", "HeadShell", "Body"}
REQUIRED_MATERIALS = {"EyeScreen"}
REQUIRED_CLIPS = {
    "idle", "talk", "listen", "think", "happy", "nod", "shake_head", "signature_wave", "celebrate",
    "dance", "wake_up", "sleep",
    # games (docs/GAMES.md §2)
    "act_bird", "act_boxer", "act_swimmer", "act_dancer", "act_robot", "act_sleeping",
    "act_superhero", "act_drummer", "duel_ready", "duel_draw", "duel_hit", "duel_win",
    "sad", "shrug", "bow",
}
REQUIRED_BONES = {
    "root", "hips", "spine", "head",
    *(f"{b}.{s}" for b in ("shoulder", "elbow", "hand", "thigh", "shin", "foot") for s in ("L", "R")),
}


def export() -> None:
    supported = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    options = {k: v for k, v in EXPORT_OPTIONS.items() if k in supported}
    bpy.ops.export_scene.gltf(filepath=str(GLB_PATH), **options)


def verify(path: Path) -> list[str]:
    gltf = read_glb_json(path)
    problems = []
    size = path.stat().st_size
    tris = count_triangles(gltf)
    if size > MAX_BYTES:
        problems.append(f"file is {size / 1e6:.2f} MB (limit {MAX_BYTES / 1e6:.0f} MB)")
    if tris > MAX_TRIANGLES:
        problems.append(f"{tris} triangles (limit {MAX_TRIANGLES})")
    nodes = {n.get("name", "") for n in gltf.get("nodes", [])}
    mats = {m.get("name", "") for m in gltf.get("materials", [])}
    anims = {a.get("name", "") for a in gltf.get("animations", [])}
    for label, need, have in (("nodes", REQUIRED_NODES, nodes), ("bones", REQUIRED_BONES, nodes),
                              ("materials", REQUIRED_MATERIALS, mats), ("clips", REQUIRED_CLIPS, anims)):
        missing = sorted(need - have)
        if missing:
            problems.append(f"missing {label}: {missing}")
    if not gltf.get("skins"):
        problems.append("no skin (armature) exported")
    print(f"[alpha_mini] glb: {size / 1e6:.2f} MB, {tris} triangles, {len(anims)} clips")
    return problems


def main() -> None:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))
    if bpy.data.objects.get("AlphaMiniRig") is None:
        raise RuntimeError("AlphaMiniRig not found: run rig_alpha_mini.py and animate_alpha_mini.py first")
    export()
    problems = verify(GLB_PATH)
    if problems:
        raise RuntimeError("glb check failed:\n  - " + "\n  - ".join(problems))
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--to-web" in argv:
        WEB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(GLB_PATH, WEB_PATH)
        print(f"[alpha_mini] copied to {WEB_PATH}")
    print(f"[alpha_mini] exported and verified {GLB_PATH}")


if __name__ == "__main__":
    main()
