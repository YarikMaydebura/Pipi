"""Staring contest (docs/GAMES.md §3.3): "First one to blink loses."

Virtual time + a scripted blink detector: the participant blinks N seconds after "go"
(``blink=[N]``), never (``blink=[None]``), or the camera dies (``blink=[BlinkDetectorError]``).
The robot gives up after ``rng.uniform(robot_loses_after_s)`` seconds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.games.setup import GameSetup, build_registry, load_game_setup
from pipi_brain.vision.base import BlinkDetectorError, VisionCheck

from .session_harness import GameTable, ScriptedRng, make_game_table

GAME = "staring"
GIVES_UP_S = 10.0  # the robot's random give-up time in these tests (config range 8-15 s)
Fixtures = tuple[LoadedConfig, DialogueContent, Path]


@pytest.fixture
def fx(dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path) -> Fixtures:
    return dev_config, dialogue_content, tmp_path


async def staring_table(fx: Fixtures, **kw: Any) -> GameTable:
    loaded, content, tmp_path = fx
    kw.setdefault("rng", ScriptedRng(uniforms=[GIVES_UP_S]))
    table = await make_game_table(loaded, content, tmp_path, **kw)
    base = load_game_setup(loaded.app.games)
    config = base.config.model_copy(update={"between_rounds_s": 0})
    setup = GameSetup(config, base.motions, build_registry(config))
    table.s.ctl.ctx.games = setup
    table.ctx.config = setup.config
    table.s.ctl.registry = setup.registry
    return table


def the_round(table: GameTable) -> dict[str, Any]:
    rounds = table.rounds()
    assert len(rounds) == 1
    return rounds[0]


def motions(table: GameTable) -> list[object]:
    return [arg for kind, arg in table.robot_did("motion")]


# --- detect mode (camera) ---------------------------------------------------------------------


async def test_a_blink_seen_by_the_camera_means_the_robot_wins(fx: Fixtures) -> None:
    table = await staring_table(fx, blink=[3.2])

    outcome = await table.play(GAME)

    played = the_round(table)
    assert outcome.result == "completed" and outcome.fallback is None
    assert (played["result"], played["winner"], played["mode"]) == ("robot_won", "robot", "detect")
    assert played["inputs"]["how"] == "blink_detected"
    assert played["timings"]["blink_ms"] == 3200
    assert "staring_you_blinked" in table.s.pipi_lines()
    assert table.s.blink is not None and table.s.blink.closed  # camera released at the end


async def test_no_blink_the_robot_gives_up_and_the_participant_wins(fx: Fixtures) -> None:
    table = await staring_table(fx, blink=[None])

    await table.play(GAME)

    played = the_round(table)
    assert (played["result"], played["winner"]) == ("participant_won", "participant")
    assert played["inputs"]["how"] == "robot_gave_up"
    assert played["timings"]["robot_gave_up_ms"] == 10_000
    assert "staring_you_win" in table.s.pipi_lines()


async def test_pipi_stays_silent_while_staring(fx: Fixtures) -> None:
    table = await staring_table(fx, blink=[None])

    await table.play(GAME)

    lines = table.s.pipi_lines()
    go, result = lines.index("staring_go"), lines.index("staring_you_win")
    assert result == go + 1  # nothing said between "go" and the result
    assert table.s.data("game_rule_blocked") == []


# --- pretend mode ------------------------------------------------------------------------------


async def test_no_face_in_view_switches_to_pretend_mode(fx: Fixtures) -> None:
    table = await staring_table(fx, blink=[], vision=VisionCheck(ok=False, reason="no face"))

    await table.play(GAME)

    played = the_round(table)
    assert played["mode"] == "pretend" and played["fallback"] == "pretend"
    fallback = table.s.data("game_fallback")[0]
    assert (fallback["to"], fallback["reason"]) == ("pretend", "no face")
    assert "staring_rules_pretend" in table.s.pipi_lines()
    assert played["inputs"]["how"] == "robot_gave_up"


async def test_without_a_camera_the_game_is_still_playable_in_pretend_mode(
    fx: Fixtures,
) -> None:
    table = await staring_table(fx)  # no blink detector at all (no webcam / not installed)

    outcome = await table.play(GAME)

    assert outcome.result == "completed" and outcome.fallback == "pretend"
    assert table.s.data("game_start")[0]["missing_requirements"] == ["camera"]


async def test_the_participant_can_admit_a_blink(fx: Fixtures) -> None:
    table = await staring_table(fx, script=[("I blinked", 4.0)])

    await table.play(GAME)

    played = the_round(table)
    assert (played["winner"], played["inputs"]["how"]) == ("robot", "admitted")
    assert "staring_admitted" in table.s.pipi_lines()


async def test_other_words_while_staring_do_not_end_the_round(fx: Fixtures) -> None:
    table = await staring_table(fx, script=[("this is hard", 2.0)])

    await table.play(GAME)

    assert the_round(table)["inputs"]["how"] == "robot_gave_up"


async def test_a_camera_that_dies_mid_round_falls_back_to_pretend(fx: Fixtures) -> None:
    table = await staring_table(fx, blink=[BlinkDetectorError("camera unplugged")])

    await table.play(GAME)

    played = the_round(table)
    assert played["fallback"] == "pretend"
    assert played["inputs"]["how"] == "robot_gave_up"
    assert "camera unplugged" in table.s.data("game_fallback")[0]["reason"]


# --- the experimenter ------------------------------------------------------------------------


async def test_the_wizard_can_score_the_round(fx: Fixtures) -> None:
    table = await staring_table(fx, blink=[None])

    async def wizard() -> None:
        await table.s.clock.sleep(2.0)
        assert (await table.s.woz("play_motion", name="stare_lose")).ok

    await table.play(GAME, meanwhile=wizard())

    played = the_round(table)
    assert (played["winner"], played["inputs"]["how"]) == ("participant", "woz")


async def test_the_robot_plays_the_staring_motions(fx: Fixtures) -> None:
    table = await staring_table(fx, blink=[None])

    await table.play(GAME)

    assert table.s.ctl.registry.implementation(GAME) is not None
    game = table.s.ctl.registry.implementation(GAME)
    assert game is not None and {"stare_ready", "stare_lose"} <= game.motions()
