"""Game clips for the fake robot: Crocodile acting (act_*), the quick-draw duel (duel_*) and a
few social reactions (sad, shrug, bow). Names match docs/GAMES.md §2 / config/motions.yaml.

Everything is built from shoulder / elbow / head / spine / leg rotations only (no squash or
hops), so the real Alpha Mini can copy the idea later. Conventions: assets/pipi3d/animate.py.
act_* clips loop (the robot keeps acting until told otherwise); duel_ready loops as a tense
stance; the rest are one-shots that end in the rest pose.
"""

from __future__ import annotations

from clip_types import Clip, Pose, arms, merge, rest, sin01, wave

_ARMS = ("shoulder.R", "shoulder.L", "elbow.R", "elbow.L")
_UPPER = ("spine", "head", *_ARMS)


def _pos(x: float) -> float:
    return max(0.0, x)


def bird_pose(p: float) -> Pose:
    """Arms out to the sides, flapping; head pecks forward."""
    flap = sin01(p, 2)
    return merge(
        arms((0, 0, 78 + 26 * flap), elbow_r=(0, 0, 14 - 14 * flap)),
        {"spine": {"rot": (-8, 0, 0)}, "head": {"rot": (4 + 8 * _pos(sin01(p, 2, 0.25)), 0, 0)}},
    )


def boxer_pose(p: float) -> Pose:
    """Guard up, alternating straight punches with a little body twist."""
    right, left = _pos(sin01(p)), _pos(-sin01(p))
    return merge(
        {"shoulder.R": {"rot": (-55 - 35 * right, 0, 8)}, "elbow.R": {"rot": (-105 + 95 * right, 0, 0)}},
        {"shoulder.L": {"rot": (-55 - 35 * left, 0, -8)}, "elbow.L": {"rot": (-105 + 95 * left, 0, 0)}},
        {"spine": {"rot": (-6, 14 * (right - left), 0)}, "head": {"rot": (-4, -8 * (right - left), 0)}},
    )


def _swim(shoulder: tuple[float, float, float], elbow: float, head: float) -> Pose:
    return merge(arms(shoulder, elbow_r=(elbow, 0, 0)),
                 {"spine": {"rot": (-18, 0, 0)}, "head": {"rot": (head, 0, 0)}})


# Breaststroke (reads from the front; a crawl arm hides behind the big head): hands together at
# the chest -> reach forward -> sweep wide to the sides -> pull back in. Head comes up to breathe.
_SWIM_TUCK = _swim((-42, 0, 8), -112, 4)
_SWIM_REACH = _swim((-92, 0, 4), -6, -4)
_SWIM_WIDE = _swim((-28, 0, 82), -10, 16)


def dancer_pose(p: float) -> Pose:
    """Ballet: arms in an arc overhead, swaying, one leg pointing out in turn."""
    sway = sin01(p)
    return merge(
        arms((0, 0, 128), elbow_r=(0, 0, 42)),
        {"spine": {"rot": (2, 0, 9 * sway)}, "hips": {"rot": (0, 0, -5 * sway)},
         "head": {"rot": (8, 0, 8 * sway)}},
        {"thigh.R": {"rot": (-18 * _pos(sway), 0, 0)}, "thigh.L": {"rot": (-18 * _pos(-sway), 0, 0)}},
    )


def sleeping_pose(p: float) -> Pose:
    """Hands together under a tilted head, slow breathing."""
    b = sin01(p)
    return merge(
        {"shoulder.R": {"rot": (-78, 0, -22)}, "elbow.R": {"rot": (-112, 0, 0)}},
        {"shoulder.L": {"rot": (-62, 0, 34)}, "elbow.L": {"rot": (-118, 0, 0)}},
        {"head": {"rot": (-6 + 1.5 * b, 0, -24)}, "spine": {"rot": (-4 + 1.5 * b, 0, -6)}},
    )


def superhero_pose(p: float) -> Pose:
    """One fist to the sky, the other on the hip, chest out, heroic sway."""
    s = sin01(p)
    return merge(
        {"shoulder.R": {"rot": (-12, 0, 152 + 5 * s)}, "elbow.R": {"rot": (0, 0, 6)}},
        {"shoulder.L": {"rot": (6, 0, -42)}, "elbow.L": {"rot": (-10, 0, 78)}},
        {"spine": {"rot": (7, 0, -6 - 2 * s)}, "head": {"rot": (14, -10, 0)}},
    )


def drummer_pose(p: float) -> Pose:
    """Forearms beat up and down in turn, head bobs to the rhythm."""
    r, l = sin01(p), sin01(p, 1, 0.5)
    return merge(
        {"shoulder.R": {"rot": (-38, 0, 10)}, "elbow.R": {"rot": (-70 - 32 * r, 0, 0)}},
        {"shoulder.L": {"rot": (-38, 0, -10)}, "elbow.L": {"rot": (-70 - 32 * l, 0, 0)}},
        {"head": {"rot": (-6 * abs(sin01(p, 1, 0.25)), 0, 4 * r)}, "spine": {"rot": (-5, 0, 0)}},
    )


_STIFF_R: Pose = {"shoulder.R": {"rot": (-88, 0, 6)}, "elbow.R": {"rot": (-88, 0, 0)}}
_STIFF_L: Pose = {"shoulder.L": {"rot": (-88, 0, -6)}, "elbow.L": {"rot": (-88, 0, 0)}}
_DOWN_R: Pose = {"shoulder.R": {"rot": (0, 0, 6)}, "elbow.R": {"rot": (-88, 0, 0)}}
_DOWN_L: Pose = {"shoulder.L": {"rot": (0, 0, -6)}, "elbow.L": {"rot": (-88, 0, 0)}}


def _robot_step(up_right: bool, head_turn: float) -> Pose:
    arm = merge(_STIFF_R, _DOWN_L) if up_right else merge(_DOWN_R, _STIFF_L)
    return merge(arm, {"head": {"rot": (0, head_turn, 0)}, "spine": {"rot": (0, 0, 0)}})


# Classic "robot dance": stiff right angles, moving in jerky steps with holds between them.
ACT_ROBOT = Clip("act_robot", 40, True, {
    0: _robot_step(True, 28), 7: _robot_step(True, 28),
    10: _robot_step(True, -28), 17: _robot_step(True, -28),
    20: _robot_step(False, -28), 27: _robot_step(False, -28),
    30: _robot_step(False, 28), 37: _robot_step(False, 28),
    40: _robot_step(True, 28),
})

ACT_BIRD = Clip("act_bird", 24, True, wave(24, 2, bird_pose))
ACT_BOXER = Clip("act_boxer", 24, True, wave(24, 2, boxer_pose))
ACT_SWIMMER = Clip("act_swimmer", 36, True, {
    0: _SWIM_TUCK, 8: _SWIM_REACH, 13: _SWIM_REACH, 24: _SWIM_WIDE, 36: _SWIM_TUCK,
})
ACT_DANCER = Clip("act_dancer", 48, True, wave(48, 4, dancer_pose))
ACT_SLEEPING = Clip("act_sleeping", 48, True, wave(48, 8, sleeping_pose))
ACT_SUPERHERO = Clip("act_superhero", 36, True, wave(36, 6, superhero_pose))
ACT_DRUMMER = Clip("act_drummer", 16, True, wave(16, 2, drummer_pose))


def ready_pose(p: float) -> Pose:
    """Gunslinger stance: hands hovering by the hips, leaning in, a tiny nervous twitch."""
    t = sin01(p, 2)
    return merge(
        arms((6, 0, 24), elbow_r=(-32 + 3 * t, 0, -26)),
        {"spine": {"rot": (-7, 0, 0)}, "head": {"rot": (-6, 0, 0)}},
    )


_READY = ready_pose(0.0)
_AIM: Pose = {"shoulder.R": {"rot": (-86, 0, 4)}, "elbow.R": {"rot": (-4, 0, 0)}}

DUEL_READY = Clip("duel_ready", 24, True, wave(24, 3, ready_pose))

DUEL_DRAW = Clip("duel_draw", 22, False, {  # whip the right arm up, aim, recoil, lower
    0: _READY,
    3: merge(_AIM, {"spine": {"rot": (-4, -6, 0)}, "head": {"rot": (-2, 0, 0)}}),
    5: {"shoulder.R": {"rot": (-98, 0, 4)}, "elbow.R": {"rot": (-18, 0, 0)}},
    8: _AIM,
    15: _AIM,
    22: rest(*_UPPER),
})

DUEL_HIT = Clip("duel_hit", 44, False, {  # hit! stagger back, arms fly up, slump, recover
    0: _READY,
    3: merge(arms((-20, 0, 95), elbow_r=(0, 0, 30)),
             {"spine": {"rot": (22, 0, 5)}, "head": {"rot": (24, 0, 0)}, "root": {"loc": (0, 0, 0.006)}}),
    8: {"spine": {"rot": (26, 0, -6)}, "head": {"rot": (20, 12, 0)}},
    15: merge(arms((-12, 0, 8), elbow_r=(-12, 0, 0)),
              {"spine": {"rot": (-26, 0, 4)}, "head": {"rot": (-30, 0, 8)}, "root": {"loc": (0, 0, 0.003)}}),
    30: merge(arms((-14, 0, 6), elbow_r=(-14, 0, 0)),
              {"spine": {"rot": (-28, 0, 4)}, "head": {"rot": (-32, 0, 8)}}),
    44: merge(rest(*_UPPER), {"root": {"loc": (0, 0, 0)}}),
})

_PUMP_UP: Pose = {"shoulder.R": {"rot": (-150, 0, 14)}, "elbow.R": {"rot": (-30, 0, 0)}}
_PUMP_DOWN: Pose = {"shoulder.R": {"rot": (-120, 0, 14)}, "elbow.R": {"rot": (-100, 0, 0)}}
DUEL_WIN = Clip("duel_win", 32, False, {  # fist pumps with the right arm, proud head
    0: _READY,
    5: merge(_PUMP_DOWN, {"spine": {"rot": (4, 0, 0)}, "head": {"rot": (10, 0, 0)},
                          "shoulder.L": {"rot": (0, 0, -12)}, "elbow.L": {"rot": (-20, 0, 0)}}),
    9: _PUMP_UP, 13: _PUMP_DOWN, 17: _PUMP_UP, 21: _PUMP_DOWN, 25: _PUMP_UP,
    32: rest(*_UPPER),
})

SAD = Clip("sad", 40, False, {  # head and shoulders drop, a slow shake of the head
    0: rest(*_UPPER),
    8: merge(arms((-8, 0, -4), elbow_r=(-6, 0, 0)), {"spine": {"rot": (-9, 0, 0)}, "head": {"rot": (-22, 0, 0)}}),
    15: {"head": {"rot": (-22, 9, 0)}},
    22: {"head": {"rot": (-22, -9, 0)}},
    29: {"head": {"rot": (-22, 0, 0)}, "spine": {"rot": (-9, 0, 0)}},
    40: rest(*_UPPER),
})

SHRUG = Clip("shrug", 26, False, {  # "no idea": forearms out, palms up, head tilted
    0: rest(*_UPPER),
    6: merge(arms((-12, 0, 30), elbow_r=(-72, 0, 28)), {"head": {"rot": (4, 0, 12)}, "spine": {"rot": (2, 0, 0)}}),
    17: merge(arms((-12, 0, 32), elbow_r=(-70, 0, 30)), {"head": {"rot": (4, 0, 12)}}),
    26: rest(*_UPPER),
})

BOW = Clip("bow", 40, False, {  # polite bow from the waist, arms slightly back
    0: rest(*_UPPER),
    10: merge(arms((16, 0, 6), elbow_r=(-6, 0, 0)), {"spine": {"rot": (-34, 0, 0)}, "head": {"rot": (-14, 0, 0)}}),
    24: merge(arms((16, 0, 6), elbow_r=(-6, 0, 0)), {"spine": {"rot": (-34, 0, 0)}, "head": {"rot": (-14, 0, 0)}}),
    40: rest(*_UPPER),
})

CLIPS = [ACT_BIRD, ACT_BOXER, ACT_SWIMMER, ACT_DANCER, ACT_ROBOT, ACT_SLEEPING, ACT_SUPERHERO,
         ACT_DRUMMER, DUEL_READY, DUEL_DRAW, DUEL_HIT, DUEL_WIN, SAD, SHRUG, BOW]
