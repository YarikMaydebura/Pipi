
exec(bpy.data.texts["am_helpers.py"].as_string())
W, G, GL, SV, DK, DG = (mat(n) for n in ["PipiWhite","PipiGrey","PipiGreyLight","PipiSilver","PipiDark","PipiDarkGrey"])
root = bpy.data.objects["AlphaMini"]
for side, sx in (("L", 1), ("R", -1)):
    x = sx * 0.465
    arm = empty(f"Arm{side}", (sx * 0.40, 0, 1.59), parent=root)
    rbox(f"ShoulderCap{side}", (0.22, 0.28, 0.17), (x - sx * 0.01, 0, 1.565), W, bevel=0.08, parent=arm)
    rbox(f"UpperArm{side}", (0.235, 0.27, 0.25), (x, 0, 1.43), W, bevel=0.075, parent=arm)
    elbow = empty(f"Elbow{side}", (x, 0, 1.30), parent=arm)
    cyl(f"ElbowRim{side}", 0.098, 0.035, (x + sx * 0.125, 0, 1.30), GL, rot=(0, math.radians(90), 0), bevel=0.012, parent=elbow)
    cyl(f"ElbowCap{side}", 0.084, 0.05, (x + sx * 0.13, 0, 1.30), W, rot=(0, math.radians(90), 0), bevel=0.02, parent=elbow)
    rbox(f"Forearm{side}", (0.255, 0.28, 0.29), (x, 0, 1.15), W, bevel=0.08, parent=elbow)
    hand = empty(f"Hand{side}", (x, 0, 1.01), parent=elbow)
    rbox(f"Palm{side}", (0.235, 0.14, 0.21), (x, 0.05, 0.90), G, bevel=0.06, parent=hand)
    rbox(f"Thumb{side}", (0.18, 0.07, 0.16), (x, -0.09, 0.925), G, bevel=0.032, parent=hand, rot=(math.radians(-12), 0, 0))
    arm.rotation_euler = (0, math.radians(-sx * 16), 0)   # negative about Y = outward for +X        # elbows out
    elbow.rotation_euler = (math.radians(-20), math.radians(sx * 8), 0)  # forearm forward, hands in
bpy.context.view_layer.update()
