"""Animation contact sheet: one labelled key frame per clip (used by render_preview.py)."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

# Most telling frame (0-based) per clip; others use the middle of the clip.
KEY_FRAMES: dict[str, int] = {
    "happy": 13, "signature_wave": 11, "jump_out": 14, "jump_in": 15, "poke": 3, "giggle": 6,
    "spin": 9, "shy": 20, "surprised": 3, "yawn": 30, "nod": 4, "shake_head": 4, "land": 2,
    "celebrate": 12, "love": 12, "look_around": 14,
}
TILE = 512
COLUMNS = 6
VIEW_DIRECTION = (0.75, -0.85, 0.30)


def clip_tracks(rig: bpy.types.Object) -> list[tuple[str, bpy.types.Action]]:
    if rig.animation_data is None:
        return []
    return [(t.name, t.strips[0].action) for t in rig.animation_data.nla_tracks if t.strips]


def reset_pose(rig: bpy.types.Object) -> None:
    rig.animation_data.action = None
    for bone in rig.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.scale = (1, 1, 1)


def make_label(extent: float, center: Vector) -> bpy.types.Object:
    curve = bpy.data.curves.new("ClipLabel", "FONT")
    curve.size = extent * 0.075
    curve.align_x = "CENTER"
    label = bpy.data.objects.new("ClipLabel", curve)
    bpy.context.scene.collection.objects.link(label)
    mat = bpy.data.materials.new("LabelInk")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0.05, 0.08, 0.09, 1)
    curve.materials.append(mat)
    label.location = center - Vector((0, 0, extent * 0.56))
    return label


def render_anim_sheet(
    cam: bpy.types.Object,
    center: Vector,
    extent: float,
    out_dir: Path,
    place_camera: Callable[[bpy.types.Object, Vector, Vector, float], None],
    load_rgba: Callable[[Path], np.ndarray],
    save_rgba: Callable[[np.ndarray, Path], None],
    over_background: Callable[[np.ndarray], np.ndarray],
) -> Path | None:
    scene = bpy.context.scene
    rig = bpy.data.objects.get("PipiRig")
    tracks = clip_tracks(rig) if rig else []
    if not tracks:
        return None
    old_res = scene.render.resolution_x, scene.render.resolution_y
    scene.render.resolution_x = scene.render.resolution_y = TILE
    framing = extent * 1.25
    place_camera(cam, Vector(VIEW_DIRECTION), center, framing)
    label = make_label(framing, center)
    label.rotation_euler = cam.rotation_euler
    tiles = []
    for name, action in tracks:
        reset_pose(rig)  # bones a clip does not animate must not keep the previous clip's pose
        rig.animation_data.action = action
        length = int(action.frame_range[1] - action.frame_range[0])
        scene.frame_set(1 + KEY_FRAMES.get(name, length // 2))
        label.data.body = name
        path = out_dir / f"anim_{name}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        tiles.append(over_background(load_rgba(path)))
    rig.animation_data.action = None
    bpy.data.objects.remove(label, do_unlink=True)
    scene.render.resolution_x, scene.render.resolution_y = old_res
    sheet = compose(tiles)
    out = out_dir / "anim_sheet.png"
    save_rgba(sheet, out)
    return out


def compose(tiles: list[np.ndarray]) -> np.ndarray:
    """Grid of tiles, first tile top-left (pixel rows are bottom-up)."""
    rows = math.ceil(len(tiles) / COLUMNS)
    blank = np.ones_like(tiles[0])
    blank[..., :3] = tiles[0][0, 0, :3]
    padded = tiles + [blank] * (rows * COLUMNS - len(tiles))
    lines = [np.concatenate(padded[r * COLUMNS:(r + 1) * COLUMNS], axis=1) for r in range(rows)]
    return np.concatenate(lines[::-1], axis=0)
