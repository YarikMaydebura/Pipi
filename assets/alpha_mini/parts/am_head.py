
exec(bpy.data.texts["am_helpers.py"].as_string())
W, G, GL, SV, DK, DG = (mat(n) for n in ["PipiWhite","PipiGrey","PipiGreyLight","PipiSilver","PipiDark","PipiDarkGrey"])
root = bpy.data.objects["AlphaMini"]
HC = Vector((0.0, 0.0, 2.08)); HR = Vector((0.305, 0.285, 0.345)); P = 3.2

def taper(nz):
    """lower face narrows toward the chin"""
    if nz >= 0: return 1.0, 1.0
    t = (-nz) ** 1.6
    return 1 - 0.15 * t, 1 - 0.05 * t

def superellipsoid(name, center, radii, p, material, segs=96, rings=64, use_taper=False, parent=None):
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0)
    for v in bm.verts:
        d = v.co.normalized()
        n = (abs(d.x) ** p + abs(d.y) ** p + abs(d.z) ** p) ** (1 / p)
        u = d / n
        sx, sy = taper(u.z) if use_taper else (1.0, 1.0)
        v.co = Vector((u.x * radii[0] * sx, u.y * radii[1] * sy, u.z * radii[2])) + Vector(center)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me); coll().objects.link(obj)
    smooth(obj); obj.data.materials.append(material)
    if parent: set_parent(obj, parent)
    return obj

def face_point(x, z):
    nz = (z - HC.z) / HR.z
    sx, sy = taper(nz)
    rest = 1 - abs(x / (HR.x * sx)) ** P - abs(nz) ** P
    return Vector((x, -HR.y * sy * max(rest, 1e-6) ** (1 / P), z))

def face_normal(x, z, e=0.004):
    dx = face_point(x + e, z) - face_point(x - e, z)
    dz = face_point(x, z + e) - face_point(x, z - e)
    n = dz.cross(dx).normalized()
    return n if n.y < 0 else -n

def orient(obj, n, axis=(0, 0, 1)):
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector(axis).rotation_difference(n)

def kill_tree(name):
    o = bpy.data.objects.get(name)
    if not o: return
    for c in list(o.children): kill_tree(c.name)
    bpy.data.objects.remove(o, do_unlink=True)

kill_tree("Head")
head = empty("Head", (0, 0, 1.72), parent=root)

# --- face shell: rounded box, flat front, wide flat chin ---
superellipsoid("HeadShell", HC, HR, P, W, segs=64, rings=44, use_taper=True, parent=head)

# --- hair cap: covers top/back, sideburns down to the ears, forehead hairline ---
HAIR_C = Vector((0.0, 0.02, 2.105)); HAIR_R = Vector((0.335, 0.315, 0.355))
hair = superellipsoid("Hair", HAIR_C, HAIR_R, 3.0, G, segs=88, rings=66)  # real-time density
bm = bmesh.new(); bm.from_mesh(hair.data)
kill = []
for f in bm.faces:
    c = f.calc_center_median()
    phi = abs(math.degrees(math.atan2(c.x, -(c.y - 0.0))))
    if c.z < 1.85:
        kill.append(f); continue
    if phi < 50:
        line = 2.165 if phi < 32 else 2.165 - 0.30 * ((phi - 32) / 18) ** 2
        if c.z < line: kill.append(f)
bmesh.ops.delete(bm, geom=kill, context="FACES")
def hairline(phi):
    return 2.165 if phi < 32 else 2.165 - 0.30 * ((phi - 32) / 18) ** 2
pH = 3.0
for v in [v for v in bm.verts if v.is_boundary]:
    phi_s = math.atan2(v.co.x, -(v.co.y - HAIR_C.y)); phi = abs(math.degrees(phi_s))
    if phi < 50 and abs(v.co.z - hairline(phi)) < 0.06:
        z = hairline(phi)
    elif abs(v.co.z - 1.85) < 0.05:
        z = 1.85
    else:
        continue
    nz = (z - HAIR_C.z) / HAIR_R.z
    rho = max(1e-6, 1 - abs(nz) ** pH) ** (1 / pH) / ((abs(math.sin(phi_s) / HAIR_R.x) ** pH + abs(math.cos(phi_s) / HAIR_R.y) ** pH) ** (1 / pH))
    v.co = Vector((rho * math.sin(phi_s), HAIR_C.y - rho * math.cos(phi_s), z))
bm.to_mesh(hair.data); bm.free()
s = hair.modifiers.new("Solidify", "SOLIDIFY"); s.thickness = 0.03; s.offset = -1; s.use_rim = True
ss = hair.modifiers.new("Subsurf", "SUBSURF"); ss.levels = 1; ss.render_levels = 2
smooth(hair); set_parent(hair, head)

# --- sculpted hair lobes (give the cap its "hairstyle" volume) ---
lobes = [
    ("HairLobeC", (0.0, -0.20, 2.315), (0.10, 0.12, 0.115), (-40, 0, 0)),
    ("HairLobeL", (0.17, -0.165, 2.295), (0.115, 0.13, 0.105), (-32, 0, -22)),
    ("HairLobeR", (-0.17, -0.165, 2.295), (0.115, 0.13, 0.105), (-32, 0, 22)),
    ("HairLobeBack", (0.0, 0.19, 2.22), (0.23, 0.13, 0.18), (12, 0, 0)),
]
for name, c, r, rot in lobes:
    o = superellipsoid(name, (0, 0, 0), r, 2.4, G, segs=40, rings=28)
    o.location = c; o.rotation_euler = tuple(math.radians(a) for a in rot)
    set_parent(o, head)

# --- ears: chunky silver octagon + grey ring + dark lens ---
for side, sx in (("L", 1), ("R", -1)):
    ex = sx * 0.318; ez = 1.985
    rot = (0, math.radians(90), 0)
    rim = cyl(f"EarRim{side}", 0.16, 0.085, (ex, 0.0, ez), SV, verts=8, bevel=0.03)
    rim.rotation_euler = (math.radians(22.5), math.radians(90), 0); set_parent(rim, head)
    cyl(f"EarRing{side}", 0.122, 0.10, (ex + sx * 0.008, 0.0, ez), G, rot=rot, verts=48, bevel=0.02, parent=head)
    lens = superellipsoid(f"EarLens{side}", (0, 0, 0), (0.06, 0.088, 0.088), 2.2, DG, segs=32, rings=20)
    lens.location = (ex + sx * 0.035, 0.0, ez); set_parent(lens, head)

# --- eyes: silver ring + round display (UV: each eye covers the full 0..1 image, EyeR mirrored;
#     same contract as Pipi's glb, so the fake robot can show Pipi's eyes) ---
def eye_disc(name, r, mirror, dome=0.012, rings=8, segs=48):
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    bm = bmesh.new(); uv = bm.loops.layers.uv.new("UVMap")
    loc = {}
    ctr = bm.verts.new((0, -dome, 0)); loc[ctr] = (0, 0)
    grid = []
    for k in range(1, rings + 1):
        rho = r * k / rings; ring = []
        for j in range(segs):
            t = 2 * math.pi * j / segs
            lx, lz = rho * math.cos(t), rho * math.sin(t)
            v = bm.verts.new((lx, -dome * (1 - (rho / r) ** 2), lz)); loc[v] = (lx, lz); ring.append(v)
        grid.append(ring)
    for j in range(segs):
        jn = (j + 1) % segs
        bm.faces.new((ctr, grid[0][jn], grid[0][j]))
        for k in range(rings - 1):
            bm.faces.new((grid[k][j], grid[k][jn], grid[k + 1][jn], grid[k + 1][j]))
    for f in bm.faces:
        for l in f.loops:
            lx, lz = loc[l.vert]; u = 0.5 + lx / (2 * r); l[uv].uv = (1 - u if mirror else u, 0.5 + lz / (2 * r))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); coll().objects.link(o); smooth(o)
    return o

eye_mat = bpy.data.materials["EyeScreen"]
EYE_X, EYE_Z = 0.150, 2.03
for side, sx, mirror in (("L", 1, False), ("R", -1, True)):
    p = face_point(sx * EYE_X, EYE_Z); n = face_normal(sx * EYE_X, EYE_Z)
    ring = cyl(f"EyeRing{side}", 0.102, 0.03, p + n * 0.004, SV, verts=64, bevel=0.008)
    orient(ring, n); set_parent(ring, head)
    eye = eye_disc(f"Eye{side}", 0.088, mirror)
    eye.data.materials.append(eye_mat)
    eye.rotation_mode = "QUATERNION"
    eye.rotation_quaternion = Vector((0, -1, 0)).rotation_difference(n)
    eye.location = p + n * 0.012
    set_parent(eye, head)

# --- mouth ---
p = face_point(0, 1.867); n = face_normal(0, 1.867)
m = rbox("Mouth", (0.09, 0.03, 0.032), p, GL, bevel=0.0155, segments=4)
m.rotation_mode = "QUATERNION"; m.rotation_quaternion = Vector((0, -1, 0)).rotation_difference(n)
set_parent(m, head)

# --- forehead camera module on the centre lobe ---
cam = rbox("ForeheadCam", (0.12, 0.07, 0.135), (0, -0.318, 2.25), DG, bevel=0.045, segments=5)
cam.rotation_euler = (math.radians(-12), 0, 0); set_parent(cam, head)
lens = cyl("ForeheadCamLens", 0.032, 0.03, (0, -0.352, 2.255), DK, rot=(math.radians(90 - 12), 0, 0), verts=40, bevel=0.006)
set_parent(lens, head)
glint = cyl("ForeheadCamGlint", 0.009, 0.01, (0.012, -0.367, 2.268), mat("PipiSilver"), rot=(math.radians(78), 0, 0), verts=16)
set_parent(glint, head)
head.scale = (1.1, 1.1, 1.1)   # big chibi head, as on the real robot
bpy.context.view_layer.update()
