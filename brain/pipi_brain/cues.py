"""The identity-cue checklist: what a participant could actually notice in this session.

docs/LOGGING_AND_STUDY.md §4. ``config.cues`` says which cues we INTEND to show; whether they
really reach the participant depends on the robot body: the fake robot shows Pipi's eyes and
plays Pipi's voice, the real Alpha Mini (Nov 24 lab test) has no known eye control and only its
built-in voice. The checklist is logged at ``session_start``; every change (e.g. the WoZ
switches to the real robot) is logged as ``cue_change``, so the analysis can read
participants' statements against what they actually saw and heard.

A robot body may report its own cues with an optional ``cue_state()`` method (same keys as
``ROBOT_CUES``, e.g. ``{"same_voice": "tts_both"}`` once the robot plays Pipi's TTS); that wins
over the defaults below. Values are never guessed: an unknown body is ``"unknown"``.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from pipi_brain.config import CuesConfig

UNKNOWN = "unknown"
ROBOT_CUES = ("same_eyes", "same_voice", "robot_camera")
# What each robot body shows when it does not say otherwise (values from docs §4).
DEFAULT_ROBOT_CUES: dict[str, dict[str, str]] = {
    # web page with Pipi's eye images; plays the same TTS audio as the pet
    "fake_robot": {"same_eyes": "display", "same_voice": "tts_both", "robot_camera": "none"},
    # measured Nov 24 (docs/ROBOT_RIDK.md §2b): no eye API known, built-in voice only
    "alpha_mini": {"same_eyes": "none", "same_voice": "builtin_robot", "robot_camera": "none"},
}


def robot_cues(robot_name: str, robot: object | None) -> dict[str, str]:
    """The robot-side cues: the body's own report, else the defaults, else unknown."""
    cues = {key: UNKNOWN for key in ROBOT_CUES} | DEFAULT_ROBOT_CUES.get(robot_name, {})
    report = getattr(robot, "cue_state", None)
    reported: Mapping[str, Any] = report() if callable(report) else {}
    return cues | {key: str(value) for key, value in reported.items() if key in ROBOT_CUES}


def cue_checklist(
    cues: CuesConfig, robot_name: str, robot: object | None, *, webcam: bool = False
) -> dict[str, Any]:
    """The checklist in the documented format (docs/LOGGING_AND_STUDY.md §4).

    ``webcam``: the laptop webcam watches the participant (staring contest) when the robot
    itself has no camera in use.
    """
    robot_side = robot_cues(robot_name, robot)
    camera = robot_side["robot_camera"]
    if webcam and camera == "none":
        camera = "webcam"
    return {
        "same_name": True,  # Pipi greets by name in both bodies ("Ta-da! Hi again, <name>!")
        "same_persona": True,  # one persona for the whole session
        "shared_memory": cues.memory_references,
        "same_eyes": robot_side["same_eyes"] if cues.same_eyes else "none",
        "same_voice": robot_side["same_voice"] if cues.same_voice else "builtin_robot",
        "signature_phrase": cues.signature_phrase,
        "signature_gesture": cues.signature_gesture,
        "transition_animation": cues.transition_animation,
        "robot_camera": camera,
        "robot_body": robot_name,
    }


def cue_changes(
    old: Mapping[str, Any], new: Mapping[str, Any], *, skip: Collection[str] = ()
) -> list[dict[str, Any]]:
    """One ``cue_change`` payload per cue whose value differs (in checklist order)."""
    return [
        {"cue": key, "old": old.get(key), "new": value}
        for key, value in new.items()
        if key not in skip and old.get(key) != value
    ]
