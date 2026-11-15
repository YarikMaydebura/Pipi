"""Render preview images of Pipi (EEVEE, transparent background, 1024x1024).

Run after build_pipi.py:
    macOS:    "$BLENDER_PATH" --background --python assets/pipi3d/render_preview.py
    Windows:  & $env:BLENDER_PATH --background --python assets/pipi3d/render_preview.py

Writes to assets/pipi3d/out/previews/:
    front.png, three_quarter.png, side.png, back.png  (1024x1024, transparent)
    sheet_views.png    2x2 contact sheet of the four views on a light background
    readability.png    the front view shrunk to 150 px tall (must still read clearly)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # Blender does not add the script folder to sys.path
    sys.path.insert(0, str(HERE))

import anim_sheet  # noqa: E402

OUT_DIR = HERE / "out"
BLEND_PATH = OUT_DIR / "pipi.blend"
PREVIEW_DIR = OUT_DIR / "previews"

RESOLUTION = 1024
LENS_MM = 85.0
FRAME_MARGIN = 1.18
SHEET_BG = (0.93, 0.94, 0.95)
READABILITY_HEIGHT_PX = 150

# direction from the model toward the camera (Pipi faces -Y)
VIEWS: dict[str, tuple[float, float, float]] = {
    "front": (0.0, -1.0, 0.12),
    "three_quarter": (0.75, -0.85, 0.30),
    "side": (1.0, 0.0, 0.10),
    "back": (0.0, 1.0, 0.15),
}


def model_bounds() -> tuple[Vector, float]:
    """Centre and largest extent of all visible geometry."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        coords = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", coords)
        ev.to_mesh_clear()
        if coords.size == 0:
            continue
        mw = np.array(ev.matrix_world)
        world = coords.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
        lo = Vector(np.minimum(np.array(lo), world.min(axis=0)))
        hi = Vector(np.maximum(np.array(hi), world.max(axis=0)))
    return (lo + hi) / 2, max(hi - lo)


def setup_render() -> None:
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    scene.render.resolution_x = scene.render.resolution_y = RESOLUTION
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"  # show the spec colours as-is (like the app)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 64
    world = scene.world or bpy.data.worlds.new("PreviewWorld")
    scene.world = world
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (0.80, 0.82, 0.85, 1.0)
    bg.inputs["Strength"].default_value = 0.45


def add_light(name: str, location: Vector, target: Vector, size: float, energy: float) -> None:
    light = bpy.data.lights.new(name, "AREA")
    light.shape = "DISK"
    light.size = size
    light.energy = energy
    obj = bpy.data.objects.new(name, light)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()


def setup_lights(center: Vector, extent: float) -> None:
    d = extent * 3.0
    k = d * d  # keep illumination constant if the model size changes
    add_light("Key", center + Vector((-0.8, -1.0, 1.0)) * d, center, extent * 2.5, 38.0 * k)
    add_light("Fill", center + Vector((1.0, -0.6, 0.3)) * d, center, extent * 3.0, 14.0 * k)
    add_light("Rim", center + Vector((0.4, 1.0, 0.9)) * d, center, extent * 2.0, 30.0 * k)


def setup_camera() -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = LENS_MM
    cam = bpy.data.objects.new("PreviewCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def place_camera(cam: bpy.types.Object, direction: Vector, center: Vector, extent: float) -> None:
    fov = 2 * math.atan(cam.data.sensor_width / (2 * cam.data.lens))
    distance = extent * FRAME_MARGIN / (2 * math.tan(fov / 2))
    cam.location = center + direction.normalized() * distance
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_start = distance * 0.05
    cam.data.clip_end = distance * 10


def render_to(path: Path) -> None:
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def load_rgba(path: Path) -> np.ndarray:
    img = bpy.data.images.load(str(path))
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)


def save_rgba(arr: np.ndarray, path: Path) -> None:
    h, w = arr.shape[:2]
    img = bpy.data.images.new(path.stem, w, h, alpha=True)
    img.pixels.foreach_set(arr.astype(np.float32).ravel())
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def over_background(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[..., 3:4]
    rgb = rgba[..., :3] * alpha + np.array(SHEET_BG, dtype=np.float32) * (1 - alpha)
    return np.concatenate([rgb, np.ones_like(alpha)], axis=-1)


def downscale(arr: np.ndarray, factor: int) -> np.ndarray:
    h, w = arr.shape[:2]
    h2, w2 = h // factor, w // factor
    return arr[: h2 * factor, : w2 * factor].reshape(h2, factor, w2, factor, 4).mean(axis=(1, 3))


def write_contact_sheet(paths: list[Path], out: Path) -> None:
    """2x2 sheet; pixel arrays are bottom-up, so the first row goes on top."""
    tiles = [downscale(over_background(load_rgba(p)), 2) for p in paths]
    top = np.concatenate(tiles[:2], axis=1)
    bottom = np.concatenate(tiles[2:4], axis=1)
    save_rgba(np.concatenate([bottom, top], axis=0), out)


def write_readability(front: Path, out: Path) -> None:
    """Crop to Pipi's height, then shrink so Pipi is ~150 px tall."""
    rgba = load_rgba(front)
    rows = np.where(rgba[..., 3].max(axis=1) > 0.02)[0]
    cols = np.where(rgba[..., 3].max(axis=0) > 0.02)[0]
    crop = rgba[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    factor = max(1, round(crop.shape[0] / READABILITY_HEIGHT_PX))
    save_rgba(downscale(over_background(crop), factor), out)


# Deformation check (--pose-test): bend every joint so stretching / gaps become visible.
# Values are local bone rotations in degrees (X, Y, Z); bone Y runs along the bone.
TEST_POSE: dict[str, tuple[float, float, float]] = {
    "head": (8.0, 0.0, 14.0),
    "antenna_base": (0.0, 0.0, -25.0),
    "antenna_tip": (0.0, 0.0, -35.0),
    "shoulder.R": (0.0, 0.0, 75.0),  # right arm out to the side (wave)
    "elbow.R": (0.0, 0.0, 70.0),  # forearm up beside the head
    "shoulder.L": (35.0, 0.0, 0.0),
    "elbow.L": (60.0, 0.0, 0.0),
    "thigh.L": (-35.0, 0.0, 0.0),
    "shin.L": (60.0, 0.0, 0.0),
}


def wants(flag: str) -> bool:
    """Script options come after '--': blender --background --python x.py -- --pose-test"""
    argv = sys.argv
    return flag in argv[argv.index("--") + 1:] if "--" in argv else False


def apply_pose(pose: dict[str, tuple[float, float, float]]) -> None:
    rig = bpy.data.objects.get("PipiRig")
    if rig is None:
        raise RuntimeError("no PipiRig in the file: run rig.py first")
    for name, degrees in pose.items():
        bone = rig.pose.bones[name]
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = tuple(math.radians(d) for d in degrees)
    bpy.context.view_layer.update()


def render_views(cam: bpy.types.Object, center: Vector, extent: float, prefix: str = "") -> list[Path]:
    paths = []
    for name, direction in VIEWS.items():
        place_camera(cam, Vector(direction), center, extent)
        path = PREVIEW_DIR / f"{prefix}{name}.png"
        render_to(path)
        paths.append(path)
    return paths


def main() -> None:
    bpy.ops.wm.open_mainfile(filepath=str(BLEND_PATH))
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    setup_render()
    pose_test = wants("--pose-test")
    if pose_test:
        apply_pose(TEST_POSE)
    center, extent = model_bounds()
    setup_lights(center, extent)
    cam = setup_camera()
    if pose_test:
        paths = render_views(cam, center, extent, prefix="pose_test_")
        write_contact_sheet(paths, PREVIEW_DIR / "sheet_pose_test.png")
    else:
        paths = render_views(cam, center, extent)
        write_contact_sheet(paths, PREVIEW_DIR / "sheet_views.png")
        write_readability(paths[0], PREVIEW_DIR / "readability.png")
        if not wants("--no-anim"):
            sheet = anim_sheet.render_anim_sheet(cam, center, extent, PREVIEW_DIR, place_camera,
                                                 load_rgba, save_rgba, over_background)
            if sheet:
                print(f"[pipi] animation sheet: {sheet}")
    print(f"[pipi] previews written to {PREVIEW_DIR}")


if __name__ == "__main__":
    main()
