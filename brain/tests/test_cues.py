"""The identity-cue checklist: what participants could actually notice (docs/LOGGING_AND_STUDY.md
§4), not only what the config intends. The analysis reads statements against it."""

from __future__ import annotations

from collections.abc import Mapping

from pipi_brain.config import CuesConfig
from pipi_brain.cues import cue_changes, cue_checklist

ALL_ON = CuesConfig(
    same_eyes=True,
    same_voice=True,
    signature_phrase=True,
    signature_gesture=True,
    memory_references=True,
    transition_animation=True,
)


class ReportingRobot:
    """A robot body that knows its own cues (Simao's AlphaMiniBody will implement this)."""

    def __init__(self, cues: Mapping[str, str]) -> None:
        self._cues = cues

    def cue_state(self) -> Mapping[str, str]:
        return self._cues


def test_the_fake_robot_shows_pipis_eyes_and_voice() -> None:
    checklist = cue_checklist(ALL_ON, "fake_robot", None)

    assert checklist["same_eyes"] == "display"
    assert checklist["same_voice"] == "tts_both"
    assert checklist["robot_body"] == "fake_robot"
    assert checklist["same_name"] is True and checklist["shared_memory"] is True


def test_the_real_robot_defaults_to_what_the_lab_measured() -> None:
    # Nov 24: no eye control known, only the built-in voice works on eduroam.
    checklist = cue_checklist(ALL_ON, "alpha_mini", object())

    assert checklist["same_eyes"] == "none"
    assert checklist["same_voice"] == "builtin_robot"


def test_a_body_that_reports_its_cues_wins_over_the_defaults() -> None:
    robot = ReportingRobot({"same_voice": "tts_both", "same_eyes": "led_colour", "junk": "x"})

    checklist = cue_checklist(ALL_ON, "alpha_mini", robot)

    assert checklist["same_voice"] == "tts_both" and checklist["same_eyes"] == "led_colour"
    assert "junk" not in checklist


def test_cues_switched_off_in_the_config_are_logged_as_off() -> None:
    off = ALL_ON.model_copy(
        update={"same_eyes": False, "same_voice": False, "memory_references": False}
    )

    checklist = cue_checklist(off, "fake_robot", None)

    assert checklist["same_eyes"] == "none"
    assert checklist["same_voice"] == "builtin_robot"
    assert checklist["shared_memory"] is False


def test_an_unknown_robot_body_is_unknown_not_guessed() -> None:
    checklist = cue_checklist(ALL_ON, "something_new", None)

    assert checklist["same_eyes"] == "unknown" and checklist["same_voice"] == "unknown"


def test_cue_changes_lists_only_what_changed() -> None:
    old = cue_checklist(ALL_ON, "fake_robot", None)
    new = cue_checklist(ALL_ON, "alpha_mini", object())

    changes = cue_changes(old, new, skip={"robot_body"})

    assert changes == [
        {"cue": "same_eyes", "old": "display", "new": "none"},
        {"cue": "same_voice", "old": "tts_both", "new": "builtin_robot"},
    ]
