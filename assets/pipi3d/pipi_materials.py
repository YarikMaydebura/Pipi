"""Pipi's materials: premium vinyl-toy look, glTF-compatible Principled BSDF only.

Imported by build_pipi.py. Colours are given as sRGB hex (design spec) and converted to the
linear values Blender's shader inputs expect. Emissive parts (eyes, cheeks, chest light,
sprout) keep their emission in the glb so the app can drive it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import bpy

SHELL_MINT_CREAM = "#E8F5EE"
JOINT_MINT = "#C9DED6"
BELLY_TEAL_GREY = "#5E7F7A"
EYE_TEAL = "#3FE0C5"
CHEEK_CORAL = "#FF8A7A"
SPROUT_GREEN = "#8EEBC0"
SCREEN_DARK = "#0C1517"


@dataclass(frozen=True)
class Look:
    color: str
    roughness: float = 0.45
    coat: float = 0.0
    coat_roughness: float = 0.1
    emission: str | None = None
    emission_strength: float = 0.0


LOOKS: dict[str, tuple[str, Look]] = {
    # key: (material name in the glb, look)
    "head": ("HeadShell", Look(SHELL_MINT_CREAM, roughness=0.42, coat=0.35, coat_roughness=0.08)),
    "shell": ("Shell", Look(SHELL_MINT_CREAM, roughness=0.45)),
    "joint": ("Joint", Look(JOINT_MINT, roughness=0.5)),
    "screen": ("FaceScreen", Look(SCREEN_DARK, roughness=0.12, coat=1.0, coat_roughness=0.03)),
    "belly": ("BellyPanel", Look(BELLY_TEAL_GREY, roughness=0.5)),
    "chest_light": ("ChestLight", Look(EYE_TEAL, roughness=0.3, emission=EYE_TEAL, emission_strength=1.5)),
    "cheek": ("Cheek", Look(CHEEK_CORAL, roughness=0.5, emission=CHEEK_CORAL, emission_strength=0.9)),
    "sprout": ("Sprout", Look(SPROUT_GREEN, roughness=0.4, emission=SPROUT_GREEN, emission_strength=0.6)),
}


def srgb_to_linear(hex_color: str) -> tuple[float, float, float]:
    v = int(hex_color.lstrip("#"), 16)
    channels = ((v >> 16) & 255, (v >> 8) & 255, v & 255)

    def conv(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    return tuple(conv(c) for c in channels)  # type: ignore[return-value]


def principled(mat: bpy.types.Material) -> bpy.types.Node:
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def make_material(name: str, look: Look) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = principled(mat)
    color = srgb_to_linear(look.color)
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = look.roughness
    bsdf.inputs["Coat Weight"].default_value = look.coat
    bsdf.inputs["Coat Roughness"].default_value = look.coat_roughness
    if look.emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*srgb_to_linear(look.emission), 1.0)
        bsdf.inputs["Emission Strength"].default_value = look.emission_strength
    mat.diffuse_color = (*color, 1.0)
    return mat


def make_image_material(name: str, image_path: Path, strength: float = 1.0) -> bpy.types.Material:
    """Swappable display (eyes, mouth): transparent except what the image draws; the image
    drives colour + glow. The app replaces the image to change expression."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = principled(mat)
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(image_path), check_existing=True)
    tex.image.alpha_mode = "STRAIGHT"
    tex.interpolation = "Linear"
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    bsdf.inputs["Emission Strength"].default_value = strength
    bsdf.inputs["Roughness"].default_value = 0.2
    if hasattr(mat, "surface_render_method"):  # Blender 4.2+
        mat.surface_render_method = "BLENDED"
    else:
        mat.blend_method = "BLEND"
    mat.use_backface_culling = True
    mat.diffuse_color = (*srgb_to_linear(SCREEN_DARK), 1.0)  # Solid view: blend into the dark screen
    return mat


def make_all(eye_image: Path, mouth_image: Path) -> dict[str, bpy.types.Material]:
    mats = {key: make_material(name, look) for key, (name, look) in LOOKS.items()}
    mats["eye"] = make_image_material("EyeScreen", eye_image)
    mats["mouth"] = make_image_material("MouthScreen", mouth_image)
    return mats
