"""The 8 core clips from the design spec (24 fps). Conventions: see animate.py."""

from __future__ import annotations

from clip_types import Clip, Pose, arms, merge, rest, sin01, wave


def idle_pose(p: float) -> Pose:
    """3 s loop: breathing bob, slight sway, antenna wobble."""
    return merge(
        {"spine": {"loc": (0, 0.0012 * (0.5 + 0.5 * sin01(p, 2)), 0), "rot": (0, 0, 1.5 * sin01(p))}},
        {"head": {"rot": (2 * sin01(p, 1, 0.25), 0, -2 * sin01(p))}},
        {"antenna_base": {"rot": (0, 0, 6 * sin01(p, 1, -0.1))}},
        {"antenna_tip": {"rot": (0, 0, 9 * sin01(p, 1, -0.2))}},
        arms((0, 0, 3 + 2 * sin01(p, 2))),
    )


def talk_pose(p: float) -> Pose:
    """1 s loop: small head bobs and lively hands while speaking."""
    return merge(
        {"head": {"rot": (4 * sin01(p, 2), 0, 3 * sin01(p))}},
        {"spine": {"rot": (-1.5 * sin01(p, 2), 0, 1.0 * sin01(p, 1, 0.3))}},
        {"antenna_base": {"rot": (-5 * sin01(p, 2, -0.15), 0, 0)}},
        {"antenna_tip": {"rot": (-7 * sin01(p, 2, -0.3), 0, 0)}},
        arms(r=(-12 - 6 * sin01(p), 0, 8 + 4 * sin01(p, 2)), l=(-6 + 5 * sin01(p, 1, 0.5), 0, -6),
             elbow_r=(-18 - 8 * sin01(p, 1, 0.2), 0, 0), elbow_l=(-10, 0, 0)),
    )


def think_pose(p: float) -> Pose:
    """Loop: head tilted and looking up, right hand at the chin, antenna droops a little."""
    return merge(
        {"head": {"rot": (8, 0, 12 + 2 * sin01(p))}},
        {"spine": {"rot": (3, 0, 1.5 * sin01(p))}},
        {"antenna_base": {"rot": (-12, 0, 3 * sin01(p, 1, -0.2))}},
        {"antenna_tip": {"rot": (-16, 0, 5 * sin01(p, 1, -0.35))}},
        arms(r=(-60, 0, -12), l=(-18, 0, 4), elbow_r=(-100 + 4 * sin01(p, 2), 0, 0), elbow_l=(-35, 0, 0)),
    )


def sleep_pose(p: float) -> Pose:
    """Loop: slumped, slow breathing, antenna drooping forward."""
    b = sin01(p)
    return merge(
        {"spine": {"rot": (-12 + 2 * b, 0, 2)}},
        {"head": {"rot": (-18 + 2.5 * b, 0, 10)}},
        {"antenna_base": {"rot": (-35 + 3 * b, 0, 4)}},
        {"antenna_tip": {"rot": (-30 + 4 * sin01(p, 1, -0.2), 0, 0)}},
        arms((-12, 0, -3), elbow_r=(-10, 0, 0)),
    )


IDLE = Clip("idle", 72, True, wave(72, 6, idle_pose))
TALK = Clip("talk", 24, True, wave(24, 3, talk_pose))
THINK = Clip("think", 48, True, {0: rest("head", "spine", "antenna_base", "antenna_tip", "shoulder.R",
                                          "shoulder.L", "elbow.R", "elbow.L"),
                                  **{f: think_pose(f / 48) for f in range(8, 48, 8)},
                                  48: rest("head", "spine", "antenna_base", "antenna_tip", "shoulder.R",
                                           "shoulder.L", "elbow.R", "elbow.L")})
SLEEP = Clip("sleep", 72, True, wave(72, 12, sleep_pose))

_HOP_BONES = ("root", "head", "antenna_tip", "shoulder.R", "shoulder.L", "elbow.R", "elbow.L")
HAPPY = Clip("happy", 24, False, {
    0: rest(*_HOP_BONES),
    4: merge({"root": {"loc": (0, 0, 0), "scale": (1.12, 0.86, 1.12)}}, arms((0, 0, 20)),
             {"antenna_tip": {"rot": (0, 0, -20)}}),
    9: merge({"root": {"loc": (0, 0.022, 0), "scale": (0.94, 1.08, 0.94)}}, arms((0, 0, 95), elbow_r=(0, 0, 30)),
             {"head": {"rot": (8, 0, 0)}, "antenna_tip": {"rot": (0, 0, 25)}}),
    13: merge({"root": {"loc": (0, 0.024, 0), "scale": (1, 1, 1)}}, arms((0, 0, 100), elbow_r=(0, 0, 40)),
              {"antenna_tip": {"rot": (0, 0, -20)}}),
    17: merge({"root": {"loc": (0, 0, 0), "scale": (1.1, 0.9, 1.1)}}, arms((0, 0, 70), elbow_r=(0, 0, 20)),
              {"head": {"rot": (4, 0, 0)}, "antenna_tip": {"rot": (0, 0, 25)}}),
    21: merge({"root": {"scale": (0.98, 1.02, 0.98)}}, {"antenna_tip": {"rot": (0, 0, -10)}}),
    24: rest(*_HOP_BONES),
})

# Wave: ONLY shoulder.R + elbow.R move (the physical robot must copy it), plus antenna wiggle.
_WAVE_ELBOW = {11: 95, 15: 55, 19: 95, 23: 55, 27: 95}
SIGNATURE_WAVE = Clip("signature_wave", 36, False, {
    0: rest("shoulder.R", "elbow.R", "antenna_base", "antenna_tip"),
    7: {"shoulder.R": {"rot": (0, 0, 78)}, "elbow.R": {"rot": (0, 0, 55)}},
    **{f: merge({"elbow.R": {"rot": (0, 0, a)}},
                {"antenna_base": {"rot": (0, 0, 10 if a > 60 else -10)},
                 "antenna_tip": {"rot": (0, 0, 16 if a > 60 else -16)}})
       for f, a in _WAVE_ELBOW.items()},
    31: merge({"shoulder.R": {"rot": (0, 0, 78)}, "elbow.R": {"rot": (0, 0, 60)}},
              {"antenna_base": {"rot": (0, 0, 0)}, "antenna_tip": {"rot": (0, 0, 0)}}),
    36: rest("shoulder.R", "elbow.R", "antenna_base", "antenna_tip"),
})

_TUCK = {"thigh.L": {"rot": (-40, 0, 0)}, "thigh.R": {"rot": (-40, 0, 0)},
         "shin.L": {"rot": (60, 0, 0)}, "shin.R": {"rot": (60, 0, 0)}}
_LEGS_REST = rest("thigh.L", "thigh.R", "shin.L", "shin.R")
_JUMP_BONES = ("root", "spine", "head", "shoulder.R", "shoulder.L")

JUMP_OUT = Clip("jump_out", 29, False, {  # turn to +X, crouch with squash, leap up and out to +X
    0: merge(rest(*_JUMP_BONES), _LEGS_REST),
    6: {"root": {"loc": (0, 0, 0), "rot": (0, 70, 0), "scale": (1, 1, 1)}},
    11: merge({"root": {"scale": (1.15, 0.80, 1.15)}, "spine": {"rot": (-10, 0, 0)}, "head": {"rot": (-5, 0, 0)}},
              arms((40, 0, 8)), _LEGS_REST),
    14: merge({"root": {"loc": (-0.03, 0.03, 0), "scale": (0.85, 1.22, 0.85)}, "spine": {"rot": (4, 0, 0)}},
              arms((-80, 0, 15))),
    20: merge({"root": {"loc": (-0.14, 0.11, 0), "scale": (0.88, 1.15, 0.88)}}, _TUCK),
    29: merge({"root": {"loc": (-0.32, 0.12, 0), "rot": (0, 70, 0), "scale": (0.90, 1.12, 0.90)}}, _TUCK),
})

JUMP_IN = Clip("jump_in", 29, False, {  # leap in from +X, land with squash, little shake
    0: merge({"root": {"loc": (-0.32, 0.12, 0), "rot": (0, -60, 0), "scale": (0.90, 1.12, 0.90)}}, _TUCK,
             arms((-70, 0, 20)), rest("spine", "head", "antenna_tip")),
    9: {"root": {"loc": (-0.12, 0.10, 0)}},
    15: merge({"root": {"loc": (0, 0, 0), "scale": (1.20, 0.78, 1.20)}}, _LEGS_REST, arms((0, 0, 30))),
    18: {"root": {"scale": (0.95, 1.06, 0.95), "rot": (0, -30, 0)}},
    21: {"root": {"scale": (1, 1, 1), "rot": (0, 0, 0)}, "spine": {"rot": (0, 0, 8)},
         "antenna_tip": {"rot": (0, 0, -25)}},
    23: {"spine": {"rot": (0, 0, -8)}, "antenna_tip": {"rot": (0, 0, 25)}},
    25: {"spine": {"rot": (0, 0, 5)}, "antenna_tip": {"rot": (0, 0, -12)}},
    27: merge(arms((0, 0, 25)), {"spine": {"rot": (0, 0, 0)}}),
    29: merge(rest(*_JUMP_BONES, "antenna_tip"), _LEGS_REST),
})

CLIPS = [IDLE, TALK, THINK, HAPPY, SIGNATURE_WAVE, JUMP_OUT, JUMP_IN, SLEEP]
