"""Build Pipi's 3D model from scratch (shapes + materials).

Pipi is our own original character: a small chibi robot companion. Everything is generated
from code so the model is reproducible and reviewable.

Run headless (Blender 4.2 LTS or newer):
    macOS:    "$BLENDER_PATH" --background --python assets/pipi3d/build_pipi.py
    Windows:  & $env:BLENDER_PATH --background --python assets/pipi3d/build_pipi.py

Output: assets/pipi3d/out/pipi.blend  (the script clears the scene first, so it is idempotent).

Conventions: metres, Z up, Pipi faces -Y, origin at the centre between the feet,
robot's left = +X. Total height (feet to sprout tip) = 0.30 m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # Blender does not add the script folder to sys.path
    sys.path.insert(0, str(HERE))

import eye_images  # noqa: E402
import mouth_images  # noqa: E402
import pipi_materials  # noqa: E402

OUT_DIR = HERE / "out"
BLEND_PATH = OUT_DIR / "pipi.blend"

TOTAL_HEIGHT = 0.30


# --------------------------------------------------------------------------------------
# Shape definitions
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SuperEllipsoid:
    """|x/a|^p + |y/b|^p + |z/c|^p = 1 around `center`; `taper` narrows x/y toward the top."""

    center: tuple[float, float, float]
    radii: tuple[float, float, float]
    power: float = 2.0
    taper: float = 0.0  # x/y scale = 1 - taper * nz  (nz in [-1, 1])

    def xy_scale(self, nz: float) -> float:
        return 1.0 - self.taper * nz

    def front_y(self, x: float, z: float) -> float | None:
        """Y of the front (-Y) surface at world (x, z), or None if outside the silhouette."""
        a, b, c = self.radii
        cx, cy, cz = self.center
        nz = (z - cz) / c
        s = self.xy_scale(nz)
        rest = 1.0 - abs((x - cx) / (a * s)) ** self.power - abs(nz) ** self.power
        if rest <= 0:
            return None
        return cy - b * s * rest ** (1.0 / self.power)


# power ~4.5 = rounded cube (flat front/sides, soft corners) rather than a balloon
HEAD = SuperEllipsoid(center=(0.0, 0.0, 0.199), radii=(0.077, 0.060, 0.066), power=4.5)
BODY = SuperEllipsoid(center=(0.0, 0.0, 0.088), radii=(0.043, 0.037, 0.046), power=2.3, taper=0.10)

FACE_SCREEN = dict(center=(0.0, 0.210), half=(0.0545, 0.0400), roundness=4.0, lift=0.0005)
# each eye mesh is a square "display" that shows one eye image (eye drawn at 40% x 60%)
EYE = dict(offset_x=0.0265, z=0.216, half=(0.024, 0.024), roundness=10.0, lift=0.0020)
MOUTH = dict(z=0.183, half=(0.016, 0.016), roundness=10.0, lift=0.0016)
CHEEK = dict(offset_x=0.047, z=0.159, radius=0.0085, lift=0.0010)
BELLY = dict(center=(0.0, 0.082), half=(0.026, 0.028), roundness=2.6, lift=0.0010)
CHEST_LIGHT = dict(z=0.104, radius=0.0065, lift=0.0024)

SHOULDER_X, SHOULDER_Z = 0.045, 0.117
HAND_POS = (0.063, -0.002, 0.074)
LEG_X = 0.022


# --------------------------------------------------------------------------------------
# Scene + helpers
# --------------------------------------------------------------------------------------


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"


def new_object(name: str, mesh: bpy.types.Mesh, mat: bpy.types.Material) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(mat)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def superellipsoid_mesh(name: str, shape: SuperEllipsoid, segments: int = 48, rings: int = 32) -> bpy.types.Mesh:
    """UV sphere pushed onto a (tapered) superellipsoid surface."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=1.0)
    a, b, c = shape.radii
    p = shape.power
    for v in bm.verts:
        d = v.co.normalized()
        norm = (abs(d.x) ** p + abs(d.y) ** p + abs(d.z) ** p) ** (1.0 / p)
        u = d / norm
        s = shape.xy_scale(u.z)
        v.co = Vector((u.x * a * s, u.y * b * s, u.z * c)) + Vector(shape.center)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def superellipse_point(theta: float, half_w: float, half_h: float, q: float) -> tuple[float, float]:
    c, s = math.cos(theta), math.sin(theta)
    return (
        half_w * math.copysign(abs(c) ** (2.0 / q), c),
        half_h * math.copysign(abs(s) ** (2.0 / q), s),
    )


def surface_patch(
    name: str,
    surface: SuperEllipsoid,
    center_xz: tuple[float, float],
    half: tuple[float, float],
    roundness: float,
    lift: float,
    mirror_u: bool = False,
    rings: int = 10,
    segments: int = 64,
) -> bpy.types.Mesh:
    """A rounded-rectangle patch moulded onto the front of `surface`, lifted by `lift`.

    UVs cover the full 0..1 square (optionally mirrored), so one square image fills it.
    """
    cx, cz = center_xz
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    uv_of: dict[bmesh.types.BMVert, tuple[float, float]] = {}

    def add_vert(x: float, z: float) -> bmesh.types.BMVert:
        y = surface.front_y(x, z)
        if y is None:
            raise ValueError(f"{name}: point ({x:.3f}, {z:.3f}) is outside the surface")
        vert = bm.verts.new((x, y - lift, z))
        u = 0.5 + (x - cx) / (2 * half[0])
        uv_of[vert] = (1.0 - u if mirror_u else u, 0.5 + (z - cz) / (2 * half[1]))
        return vert

    center = add_vert(cx, cz)
    grid = []
    for k in range(1, rings + 1):
        t = k / rings
        ring = []
        for j in range(segments):
            px, pz = superellipse_point(2 * math.pi * j / segments, half[0] * t, half[1] * t, roundness)
            ring.append(add_vert(cx + px, cz + pz))
        grid.append(ring)
    for j in range(segments):
        jn = (j + 1) % segments
        bm.faces.new((center, grid[0][j], grid[0][jn]))
        for k in range(rings - 1):
            bm.faces.new((grid[k][j], grid[k + 1][j], grid[k + 1][jn], grid[k][jn]))
    for face in bm.faces:
        for loop in face.loops:
            loop[uv_layer].uv = uv_of[loop.vert]
    bm.normal_update()
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def capsule_between(
    name: str, start: Vector, end: Vector, r_start: float, r_end: float, mat: bpy.types.Material
) -> bpy.types.Object:
    """Tapered rounded capsule from `start` to `end`."""
    length = (end - start).length
    shape = SuperEllipsoid(center=(0, 0, 0), radii=(1.0, 1.0, 1.0), power=2.4)
    mesh = superellipsoid_mesh(name, shape, segments=24, rings=16)
    half = length / 2 + max(r_start, r_end) * 0.6
    for v in mesh.vertices:
        t = (v.co.z + 1.0) / 2.0  # 0 at start, 1 at end
        r = r_start + (r_end - r_start) * t
        v.co = Vector((v.co.x * r, v.co.y * r, v.co.z * half))
    obj = new_object(name, mesh, mat)
    direction = (end - start).normalized()
    rot = Vector((0, 0, 1)).rotation_difference(direction).to_matrix().to_4x4()
    obj.matrix_world = Matrix.Translation((start + end) / 2) @ rot
    return obj


def ellipsoid_at(
    name: str, center: tuple[float, float, float], radii: tuple[float, float, float],
    mat: bpy.types.Material, power: float = 2.0, segments: int = 32, rings: int = 20,
) -> bpy.types.Object:
    shape = SuperEllipsoid(center=center, radii=radii, power=power)
    return new_object(name, superellipsoid_mesh(name, shape, segments, rings), mat)


# --------------------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------------------


def build_head(m: dict[str, bpy.types.Material]) -> None:
    new_object("Head", superellipsoid_mesh("Head", HEAD, segments=48, rings=32), m["head"])
    screen = new_object(
        "FaceScreen",
        surface_patch("FaceScreen", HEAD, FACE_SCREEN["center"], FACE_SCREEN["half"],
                      FACE_SCREEN["roundness"], FACE_SCREEN["lift"], rings=4, segments=48),
        m["screen"],
    )
    solid = screen.modifiers.new("Thickness", "SOLIDIFY")
    solid.thickness = 0.0008
    solid.offset = 1.0
    for side, sign in (("L", 1.0), ("R", -1.0)):
        new_object(
            f"Eye{side}",
            surface_patch(f"Eye{side}", HEAD, (sign * EYE["offset_x"], EYE["z"]), EYE["half"],
                          EYE["roundness"], EYE["lift"], mirror_u=(side == "R"), rings=4, segments=40),
            m["eye"],
        )
        new_object(
            f"Cheek{side}",
            surface_patch(f"Cheek{side}", HEAD, (sign * CHEEK["offset_x"], CHEEK["z"]),
                          (CHEEK["radius"], CHEEK["radius"]), 2.0, CHEEK["lift"], rings=3, segments=32),
            m["cheek"],
        )
    new_object(
        "Mouth",
        surface_patch("Mouth", HEAD, (0.0, MOUTH["z"]), MOUTH["half"], MOUTH["roundness"],
                      MOUTH["lift"], rings=3, segments=32),
        m["mouth"],
    )


def build_antenna(m: dict[str, bpy.types.Material]) -> None:
    top_z = HEAD.center[2] + HEAD.radii[2]
    ellipsoid_at("AntennaBase", (0.0, 0.002, top_z - 0.001), (0.0075, 0.0075, 0.004), m["shell"])
    curve = bpy.data.curves.new("Antenna", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.0029
    curve.bevel_resolution = 2
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(1)
    p0, p1 = spline.bezier_points
    p0.co = (0.0, 0.002, top_z)
    p0.handle_left, p0.handle_right = (0.0, 0.002, top_z - 0.005), (0.0, 0.002, top_z + 0.013)
    for point in (p0, p1):
        point.handle_left_type = point.handle_right_type = "FREE"
    p1.co = (0.0040, 0.001, top_z + 0.023)
    p1.handle_left, p1.handle_right = (0.0005, 0.002, top_z + 0.018), (0.007, 0.0, top_z + 0.027)
    curve_obj = bpy.data.objects.new("AntennaCurve", curve)
    bpy.context.scene.collection.objects.link(curve_obj)
    curve.materials.append(m["joint"])
    curve_to_mesh(curve_obj, "Antenna")
    build_sprout(Vector(p1.co), m)


def curve_to_mesh(curve_obj: bpy.types.Object, name: str) -> bpy.types.Object:
    """Replace a curve object with a plain mesh (needed for skinning and glTF)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(curve_obj.evaluated_get(depsgraph))
    mesh.name = name
    obj = bpy.data.objects.new(name, mesh)
    obj.matrix_world = curve_obj.matrix_world
    bpy.context.scene.collection.objects.link(obj)
    for poly in mesh.polygons:
        poly.use_smooth = True
    bpy.data.objects.remove(curve_obj, do_unlink=True)
    return obj


def build_sprout(tip: Vector, m: dict[str, bpy.types.Material]) -> None:
    """Two small pointed leaves at the antenna tip, joined into one 'Sprout' object."""
    half_len = 0.0088
    leaves = []
    for name, angle in (("LeafA", -48.0), ("LeafB", 50.0)):
        shape = SuperEllipsoid(center=(0, 0, 0), radii=(0.0056, 0.0017, half_len), power=2.0)
        mesh = superellipsoid_mesh(name, shape, segments=16, rings=10)
        for v in mesh.vertices:
            nz = max(-1.0, min(1.0, v.co.z / half_len))
            ellipse_width = math.sqrt(max(1e-6, 1.0 - nz * nz))
            leaf_width = math.sin(math.pi * (nz + 1.0) / 2.0) ** 1.3  # pointed at both ends
            v.co.x *= leaf_width / ellipse_width
            v.co.z += half_len  # the leaf grows up from its base
        obj = new_object(name, mesh, m["sprout"])
        obj.matrix_world = Matrix.Translation(tip) @ Matrix.Rotation(math.radians(angle), 4, "Y")
        leaves.append(obj)
    join(leaves, "Sprout")


def build_body(m: dict[str, bpy.types.Material]) -> None:
    new_object("Body", superellipsoid_mesh("Body", BODY, segments=40, rings=24), m["shell"])
    new_object(
        "BellyPanel",
        surface_patch("BellyPanel", BODY, BELLY["center"], BELLY["half"], BELLY["roundness"],
                      BELLY["lift"], rings=3, segments=40),
        m["belly"],
    )
    new_object(
        "ChestLight",
        surface_patch("ChestLight", BODY, (0.0, CHEST_LIGHT["z"]),
                      (CHEST_LIGHT["radius"], CHEST_LIGHT["radius"]), 2.0, CHEST_LIGHT["lift"],
                      rings=3, segments=32),
        m["chest_light"],
    )


def build_arms(m: dict[str, bpy.types.Material]) -> None:
    for side, sign in (("L", 1.0), ("R", -1.0)):
        shoulder = Vector((sign * SHOULDER_X, 0.0, SHOULDER_Z))
        hand = Vector((sign * HAND_POS[0], HAND_POS[1], HAND_POS[2]))
        ellipsoid_at(f"Shoulder{side}", tuple(shoulder), (0.0105, 0.0105, 0.0105), m["joint"])
        arm_start = shoulder + Vector((sign * 0.003, 0.0, -0.004))
        arm_end = hand + Vector((-sign * 0.001, 0.0, 0.008))
        capsule_between(f"Arm{side}", arm_start, arm_end, 0.0105, 0.0085, m["shell"])
        ellipsoid_at(f"Hand{side}", tuple(hand), (0.0112, 0.0118, 0.0128), m["shell"], power=2.2)


def build_legs(m: dict[str, bpy.types.Material]) -> None:
    for side, sign in (("L", 1.0), ("R", -1.0)):
        x = sign * LEG_X
        capsule_between(f"Leg{side}", Vector((x, 0.0, 0.056)), Vector((x, 0.0, 0.022)), 0.0128, 0.0120, m["joint"])
        foot_shape = SuperEllipsoid(center=(0, 0, 0), radii=(0.0175, 0.0255, 0.0135), power=2.5)
        mesh = superellipsoid_mesh(f"Foot{side}", foot_shape, segments=28, rings=16)
        for v in mesh.vertices:
            if v.co.z < 0:
                v.co.z *= 0.45  # flat, stable sole
        foot = new_object(f"Foot{side}", mesh, m["shell"])
        foot.location = (sign * (LEG_X + 0.003), -0.006, 0.0135 * 0.45)


def join(objects: list[bpy.types.Object], name: str) -> bpy.types.Object:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = name
    joined.data.name = name
    return joined


def report() -> None:
    meshes = [o for o in bpy.context.scene.objects if o.type in {"MESH", "CURVE"}]
    zs, tris = [], 0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in meshes:
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        zs.extend((ev.matrix_world @ v.co).z for v in mesh.vertices)
        mesh.calc_loop_triangles()
        tris += len(mesh.loop_triangles)
        ev.to_mesh_clear()
    print(f"[pipi] objects={len(meshes)} height={max(zs) - min(zs):.4f} m "
          f"(min z {min(zs):.4f}) triangles={tris}")


def main() -> None:
    reset_scene()
    eye_paths = eye_images.write_all()
    mouth_paths = mouth_images.write_all()
    m = pipi_materials.make_all(eye_paths["idle"], mouth_paths["smile"])
    build_body(m)
    build_head(m)
    build_antenna(m)
    build_arms(m)
    build_legs(m)
    report()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.file.pack_all()  # keep eye/mouth images inside the .blend (works when moved)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    print(f"[pipi] saved {BLEND_PATH}")


if __name__ == "__main__":
    main()
