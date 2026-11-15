
exec(bpy.data.texts["am_helpers.py"].as_string())
body = bpy.data.objects["Body"]
rx = math.radians(90)
y0 = -0.246
cyl("BadgeRim", 0.082, 0.012, (0, y0, 1.41), mat("PipiDark"), rot=(rx, 0, 0), verts=64, bevel=0.004, parent=body)
tip = rbox("BadgeTip", (0.075, 0.012, 0.075), (0, y0, 1.465), mat("PipiDark"), bevel=0.02, segments=4, rot=(0, math.radians(45), 0), parent=body)
cyl("Badge", 0.064, 0.016, (0, y0 - 0.004, 1.405), mat("PipiWhite"), rot=(rx, 0, 0), verts=64, bevel=0.004, parent=body)
for i, (dx, dz) in enumerate([(0, -0.004), (-0.03, 0.026), (0.03, 0.026), (0.0, -0.036)]):
    cyl(f"BadgeDot{i}", 0.011, 0.01, (dx, y0 - 0.014, 1.405 + dz), mat("PipiBlueGlow"), rot=(rx, 0, 0), verts=24, parent=body)
cyl("MicDot", 0.006, 0.01, (0, -0.236, 1.28), mat("PipiDark"), rot=(rx, 0, 0), verts=16, parent=body)
bpy.context.view_layer.update()
