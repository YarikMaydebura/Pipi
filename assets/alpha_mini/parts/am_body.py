
exec(bpy.data.texts["am_helpers.py"].as_string())
W, G, GL, SV, DK, DG = (mat(n) for n in ["PipiWhite","PipiGrey","PipiGreyLight","PipiSilver","PipiDark","PipiDarkGrey"])
root = empty("AlphaMini", (0, 0, 0)); root.empty_display_size = 0.4
for side, sx in (("L", 1), ("R", -1)):
    x = 0.19 * sx
    leg = empty(f"Leg{side}", (x, 0, 0.95), parent=root)
    rbox(f"Thigh{side}", (0.30, 0.34, 0.37), (x, 0.0, 0.765), W, bevel=0.07, parent=leg)
    rbox(f"KneePad{side}", (0.245, 0.03, 0.10), (x, -0.172, 0.625), G, bevel=0.048, parent=leg)
    cyl(f"Knee{side}", 0.10, 0.30, (x, 0.01, 0.555), GL, rot=(0, math.radians(90), 0), bevel=0.02, parent=leg)
    rbox(f"Shin{side}", (0.28, 0.32, 0.27), (x, 0.0, 0.405), W, bevel=0.07, parent=leg)
    cyl(f"Ankle{side}", 0.085, 0.29, (x, 0.02, 0.235), GL, rot=(0, math.radians(90), 0), bevel=0.02, parent=leg)
    rbox(f"Foot{side}", (0.42, 0.66, 0.16), (x + 0.045 * sx, -0.07, 0.11), W, bevel=0.075, parent=leg)
    rbox(f"Sole{side}", (0.43, 0.67, 0.035), (x + 0.045 * sx, -0.07, 0.0175), G, bevel=0.016, parent=leg)
rbox("Pelvis", (0.68, 0.42, 0.14), (0, 0.0, 0.97), W, bevel=0.06, parent=root)
body = rbox("Body", (0.675, 0.46, 0.66), (0, 0.0, 1.365), W, bevel=0.11, parent=root)
rbox("WaistSeam", (0.66, 0.45, 0.014), (0, 0.0, 1.04), GL, bevel=0.006, parent=body)
rbox("ChestPanelFrame", (0.40, 0.02, 0.57), (0, -0.222, 1.35), GL, bevel=0.09, parent=body)
rbox("ChestPanel", (0.37, 0.03, 0.54), (0, -0.228, 1.35), G, bevel=0.085, parent=body)
rbox("BackPack", (0.50, 0.06, 0.50), (0, 0.245, 1.37), GL, bevel=0.06, parent=body)
for i in range(3):
    rbox(f"BackVent{i}", (0.16, 0.02, 0.014), (0, 0.278, 1.30 + i * 0.035), DG, bevel=0.006, parent=body)
cyl("Neck", 0.115, 0.10, (0, 0.0, 1.72), G, bevel=0.01, parent=root)
