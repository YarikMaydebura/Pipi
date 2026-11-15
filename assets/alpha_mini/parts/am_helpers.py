
import bpy, bmesh, math
from mathutils import Vector, Matrix

COLL_NAME = "AlphaMini"

def coll():
    c = bpy.data.collections.get(COLL_NAME)
    if c is None:
        c = bpy.data.collections.new(COLL_NAME)
        bpy.context.scene.collection.children.link(c)
    return c

def principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")

def make_mat(name, color, rough=0.4, metal=0.0, coat=0.0, emit=None, emit_strength=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    p = principled(m)
    p.inputs["Base Color"].default_value = (*color, 1.0)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    if "Coat Weight" in p.inputs:
        p.inputs["Coat Weight"].default_value = coat
    if emit is not None:
        p.inputs["Emission Color"].default_value = (*emit, 1.0)
        p.inputs["Emission Strength"].default_value = emit_strength
    m.diffuse_color = (*color, 1.0)
    return m

def mat(name):
    return bpy.data.materials[name]

def link(obj, parent=None):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll().objects.link(obj)
    if parent is not None:
        set_parent(obj, parent)
    return obj

def world_of(obj):
    if obj.parent is None:
        return obj.matrix_basis.copy()
    return world_of(obj.parent) @ obj.matrix_parent_inverse @ obj.matrix_basis

def set_parent(obj, parent):
    """Parent keeping the object's world transform (fresh objects: basis == world)."""
    obj.parent = parent
    obj.matrix_parent_inverse = world_of(parent).inverted()

def smooth(obj):
    for p in obj.data.polygons:
        p.use_smooth = True

def rbox(name, dims, loc, material, bevel=0.06, segments=5, parent=None, rot=(0, 0, 0)):
    """Rounded box: real dimensions, bevelled edges, smooth shading."""
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * dims[0], v.co.y * dims[1], v.co.z * dims[2]))
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    obj.rotation_euler = rot
    coll().objects.link(obj)
    b = obj.modifiers.new("Bevel", "BEVEL")
    b.width = min(bevel, min(dims) * 0.49)
    b.segments = segments
    b.limit_method = "NONE"
    b.harden_normals = False
    smooth(obj)
    obj.data.materials.append(material)
    if parent is not None:
        set_parent(obj, parent)
    return obj

def ellipsoid(name, radii, loc, material, parent=None, segs=48, rings=32):
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * radii[0], v.co.y * radii[1], v.co.z * radii[2]))
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    coll().objects.link(obj)
    smooth(obj)
    obj.data.materials.append(material)
    if parent is not None:
        set_parent(obj, parent)
    return obj

def cyl(name, r, depth, loc, material, rot=(0, 0, 0), verts=48, bevel=0.0, parent=None):
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=verts, radius1=r, radius2=r, depth=depth)
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    obj.rotation_euler = rot
    coll().objects.link(obj)
    if bevel > 0:
        b = obj.modifiers.new("Bevel", "BEVEL"); b.width = bevel; b.segments = 4
        b.limit_method = "ANGLE"
    smooth(obj)
    obj.data.materials.append(material)
    if parent is not None:
        set_parent(obj, parent)
    return obj

def empty(name, loc, parent=None):
    old = bpy.data.objects.get(name)
    if old: bpy.data.objects.remove(old, do_unlink=True)
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "PLAIN_AXES"
    e.empty_display_size = 0.15
    e.location = loc
    coll().objects.link(e)
    if parent is not None:
        set_parent(e, parent)
    return e
