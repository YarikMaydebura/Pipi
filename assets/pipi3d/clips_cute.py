"""Extra cute reaction clips for interaction (click, drag, hover, speech, idle fidgets).

Conventions: see animate.py. One-shot clips end either at rest or in a pose the app holds
briefly before fading back to idle.
"""

from __future__ import annotations

from clip_types import Clip, Pose, arms, merge, rest, sin01, wave

_ARMS = ("shoulder.R", "shoulder.L", "elbow.R", "elbow.L")


def listen_pose(p: float) -> Pose:
    """Loop: leans in, head tilted, antenna perked up."""
    return merge(
        {"spine": {"rot": (-6 + sin01(p), 0, 0)}},
        {"head": {"rot": (4, 0, 10 + 2 * sin01(p, 1, 0.2))}},
        {"antenna_base": {"rot": (8, 0, 0)}, "antenna_tip": {"rot": (0, 0, 6 * sin01(p, 2, -0.2))}},
        arms((-8, 0, 4)),
    )


def dance_pose(p: float) -> Pose:
    """Loop: side steps, hip sway, alternating arms, head bob, bouncy antenna."""
    s = sin01(p, 2)
    return merge(
        {"root": {"loc": (0.006 * sin01(p), 0.002 * max(0.0, sin01(p, 4)), 0)}},
        {"hips": {"rot": (0, 0, 6 * sin01(p))}, "spine": {"rot": (0, 0, -4 * sin01(p))}},
        {"head": {"rot": (5 * sin01(p, 4), 0, 6 * sin01(p, 1, 0.25))}},
        {"antenna_tip": {"rot": (0, 0, 15 * sin01(p, 2, -0.1))}},
        arms(r=(-20, 0, 45 + 35 * s), l=(-20, 0, -(45 - 35 * s)),
             elbow_r=(0, 0, 40 + 20 * s), elbow_l=(0, 0, -(40 - 20 * s))),
        {"shin.L": {"rot": (20 * max(0.0, s), 0, 0)}, "shin.R": {"rot": (20 * max(0.0, -s), 0, 0)},
         "thigh.L": {"rot": (-10 * max(0.0, s), 0, 0)}, "thigh.R": {"rot": (-10 * max(0.0, -s), 0, 0)}},
    )


def dangle_pose(p: float) -> Pose:
    """Loop while dragged: legs kick, arms flail, head and antenna wobble."""
    s = sin01(p, 2)
    return merge(
        {"thigh.L": {"rot": (-30 * s, 0, 0)}, "thigh.R": {"rot": (30 * s, 0, 0)},
         "shin.L": {"rot": (30 + 20 * s, 0, 0)}, "shin.R": {"rot": (30 - 20 * s, 0, 0)}},
        arms(r=(0, 0, 50 + 20 * sin01(p, 2)), l=(0, 0, -(50 + 20 * sin01(p, 2, 0.5))),
             elbow_r=(0, 0, 30), elbow_l=(0, 0, -30)),
        {"head": {"rot": (0, 0, 6 * sin01(p))}, "antenna_tip": {"rot": (0, 0, 25 * sin01(p, 2, -0.2))}},
    )


def look_pose(head_turn: float, tip: float) -> Pose:
    return {"head": {"rot": (3 if head_turn else 0, head_turn, 0)}, "antenna_tip": {"rot": (0, 0, tip)}}


LISTEN = Clip("listen", 48, True, wave(48, 8, listen_pose))
DANCE = Clip("dance", 48, True, wave(48, 4, dance_pose))
DANGLE = Clip("dangle", 24, True, wave(24, 3, dangle_pose))

NOD = Clip("nod", 20, False, {
    0: rest("head", "antenna_tip"),
    4: {"head": {"rot": (-15, 0, 0)}},
    6: {"antenna_tip": {"rot": (12, 0, 0)}},
    8: {"head": {"rot": (2, 0, 0)}},
    10: {"antenna_tip": {"rot": (-10, 0, 0)}},
    12: {"head": {"rot": (-12, 0, 0)}},
    14: {"antenna_tip": {"rot": (8, 0, 0)}},
    20: rest("head", "antenna_tip"),
})

SHAKE_HEAD = Clip("shake_head", 24, False, {
    0: rest("head", "antenna_tip"),
    **{f: {"head": {"rot": (0, a, 0)}, "antenna_tip": {"rot": (0, 0, -0.8 * a)}}
       for f, a in {4: 18, 9: -18, 14: 15, 19: -8}.items()},
    24: rest("head", "antenna_tip"),
})

POKE = Clip("poke", 20, False, {  # click: squish + boing
    0: rest("root", "head", "antenna_tip", *_ARMS),
    3: merge({"root": {"scale": (1.14, 0.84, 1.14)}, "head": {"rot": (0, 0, -6)},
              "antenna_tip": {"rot": (0, 0, -30)}}, arms((0, 0, -6), elbow_r=(-20, 0, 0))),
    7: {"root": {"scale": (0.93, 1.09, 0.93)}, "head": {"rot": (0, 0, 8)}, "antenna_tip": {"rot": (0, 0, 35)}},
    11: {"root": {"scale": (1.04, 0.97, 1.04)}, "head": {"rot": (0, 0, -5)}, "antenna_tip": {"rot": (0, 0, -25)}},
    15: {"root": {"scale": (0.99, 1.01, 0.99)}, "head": {"rot": (0, 0, 2)}, "antenna_tip": {"rot": (0, 0, 12)}},
    20: rest("root", "head", "antenna_tip", *_ARMS),
})

GIGGLE = Clip("giggle", 24, False, {
    0: rest("spine", "head", *_ARMS),
    3: merge({"head": {"rot": (8, 0, 4)}}, arms((-25, 0, -8), elbow_r=(-60, 0, 0))),
    **{f: {"spine": {"rot": (0, 0, 5 if (f // 2) % 2 else -5)}} for f in range(4, 20, 2)},
    20: {"spine": {"rot": (0, 0, 0)}, "head": {"rot": (6, 0, 0)}},
    24: rest("spine", "head", *_ARMS),
})

SPIN = Clip("spin", 30, False, {
    0: rest("root", *_ARMS),
    3: merge({"root": {"scale": (1.08, 0.92, 1.08)}}, arms((0, 0, 70))),
    6: {"root": {"loc": (0, 0.015, 0), "rot": (0, 90, 0), "scale": (0.96, 1.05, 0.96)}},
    12: {"root": {"loc": (0, 0.020, 0), "rot": (0, 180, 0)}},
    18: {"root": {"loc": (0, 0.015, 0), "rot": (0, 270, 0)}},
    24: {"root": {"loc": (0, 0, 0), "rot": (0, 360, 0), "scale": (1.1, 0.9, 1.1)}},
    27: {"root": {"scale": (0.98, 1.02, 0.98)}},
    30: merge({"root": {"loc": (0, 0, 0), "rot": (0, 360, 0), "scale": (1, 1, 1)}}, arms((0, 0, 0))),
})

_SHY = merge(arms((-70, 0, -12), elbow_r=(-75, 0, 0)), {"head": {"rot": (-12, 0, 10)}})
SHY = Clip("shy", 36, False, {  # hands up to the face, head down, little sway
    0: rest("root", "head", *_ARMS),
    8: _SHY,
    14: {"root": {"rot": (0, 8, 0)}, "foot.R": {"rot": (0, 0, 0)}},
    20: {"root": {"rot": (0, -8, 0)}, "foot.R": {"rot": (0, 15, 0)}},
    26: {"root": {"rot": (0, 6, 0)}, "foot.R": {"rot": (0, 0, 0)}},
    32: {"root": {"rot": (0, -4, 0)}},
    36: merge(_SHY, {"root": {"rot": (0, 0, 0)}}),
})

SURPRISED = Clip("surprised", 20, False, {
    0: rest("root", "head", "antenna_base", *_ARMS),
    3: merge({"root": {"loc": (0, 0.012, 0.008), "scale": (0.92, 1.10, 0.92)}, "head": {"rot": (10, 0, 0)},
              "antenna_base": {"rot": (10, 0, 0)}}, arms((0, 0, 55), elbow_r=(0, 0, 40))),
    8: {"root": {"loc": (0, 0.004, 0.010), "scale": (1, 1, 1)}},
    12: {"root": {"loc": (0, 0, 0.010), "scale": (1.06, 0.95, 1.06)}},
    20: merge({"root": {"loc": (0, 0, 0.006), "scale": (1, 1, 1)}, "antenna_base": {"rot": (0, 0, 0)}},
              arms((0, 0, 35), elbow_r=(0, 0, 20))),
})

YAWN = Clip("yawn", 48, False, {
    0: rest("root", "spine", "head", "antenna_base", *_ARMS),
    12: merge({"root": {"scale": (0.97, 1.05, 0.97)}, "spine": {"rot": (8, 0, 0)}, "head": {"rot": (15, 0, 0)},
               "antenna_base": {"rot": (10, 0, 0)}}, arms((0, 0, 100), elbow_r=(0, 0, 10))),
    30: merge({"head": {"rot": (18, 0, 3)}}, arms((0, 0, 105), elbow_r=(0, 0, 15))),
    40: merge({"root": {"scale": (1, 1, 1)}, "spine": {"rot": (0, 0, 0)}, "head": {"rot": (-5, 0, 0)},
               "antenna_base": {"rot": (-8, 0, 0)}}, arms((0, 0, 10), elbow_r=(0, 0, 0))),
    48: rest("root", "spine", "head", "antenna_base", *_ARMS),
})

LOOK_AROUND = Clip("look_around", 72, True, {
    0: look_pose(0, 0), 12: look_pose(30, -8), 16: look_pose(30, 6), 26: look_pose(30, 0),
    36: look_pose(0, 10), 48: look_pose(-30, 8), 52: look_pose(-30, -6), 62: look_pose(-30, 0),
    72: look_pose(0, 0),
})

LAND = Clip("land", 14, False, {  # after being dropped
    0: merge({"root": {"scale": (0.93, 1.08, 0.93)}}, rest("antenna_tip", *_ARMS)),
    2: merge({"root": {"scale": (1.22, 0.76, 1.22)}, "antenna_tip": {"rot": (-30, 0, 0)}}, arms((0, 0, 35))),
    6: {"root": {"scale": (0.95, 1.06, 0.95)}, "antenna_tip": {"rot": (20, 0, 0)}},
    9: {"root": {"scale": (1.03, 0.98, 1.03)}, "antenna_tip": {"rot": (-8, 0, 0)}},
    14: merge({"root": {"scale": (1, 1, 1)}}, rest("antenna_tip", *_ARMS)),
})

_HOP = {0: 0.0, 4: 0.0, 9: 0.022, 14: 0.0, 18: 0.0, 23: 0.026, 28: 0.0}
_SQUASH = {4: (1.12, 0.88, 1.12), 14: (1.1, 0.9, 1.1), 18: (1.12, 0.88, 1.12), 28: (1.1, 0.9, 1.1)}
CELEBRATE = Clip("celebrate", 36, False, {
    **{f: {"root": {"loc": (0, y, 0), "scale": _SQUASH.get(f, (0.95, 1.06, 0.95) if y else (1, 1, 1))}}
       for f, y in _HOP.items()},
    0: merge({"root": {"loc": (0, 0, 0), "scale": (1, 1, 1)}}, rest("head", *_ARMS)),
    6: merge(arms((0, 0, 95), elbow_r=(0, 0, 30)), {"head": {"rot": (8, 0, 0)}}),
    12: arms((0, 0, 100), elbow_r=(0, 0, 50)),
    20: arms((0, 0, 95), elbow_r=(0, 0, 25)),
    26: arms((0, 0, 100), elbow_r=(0, 0, 50)),
    32: merge({"root": {"loc": (0, 0, 0), "scale": (0.98, 1.02, 0.98)}}, arms((0, 0, 40), elbow_r=(0, 0, 10))),
    36: merge({"root": {"loc": (0, 0, 0), "scale": (1, 1, 1)}}, rest("head", *_ARMS)),
})

_CLASP = arms((-35, 0, -14), elbow_r=(-55, 0, -8))
LOVE = Clip("love", 36, False, {  # hands clasped, dreamy sway (app shows heart eyes)
    0: merge(rest("spine", "head", "antenna_tip", *_ARMS)),
    6: merge(_CLASP, {"head": {"rot": (4, 0, 0)}}),
    **{f: {"spine": {"rot": (0, 0, 5 * d)}, "head": {"rot": (4, 0, 10 * d)}, "antenna_tip": {"rot": (0, 0, -12 * d)}}
       for f, d in {12: 1, 20: -1, 28: 1}.items()},
    36: merge(_CLASP, {"spine": {"rot": (0, 0, 0)}, "head": {"rot": (4, 0, 8)}, "antenna_tip": {"rot": (0, 0, 0)}}),
})

CLIPS = [LISTEN, NOD, SHAKE_HEAD, POKE, GIGGLE, SPIN, DANCE, SHY, SURPRISED, YAWN, LOOK_AROUND,
         DANGLE, LAND, CELEBRATE, LOVE]
