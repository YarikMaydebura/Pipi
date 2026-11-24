"""Arm rock-paper-scissors, voice mode (docs/GAMES.md §3.4): best of 3.

The robot's choice comes from ``rng.random()``: 0.1 = rock, 0.5 = paper, 0.9 = scissors.
The participant says (types) their choice; ``None`` = silent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.games.rps import judge, parse_choice
from pipi_brain.games.setup import GameSetup, build_registry, load_game_setup

from .session_harness import GameTable, ScriptedRng, make_game_table

GAME = "rps_arms"
ROCK, PAPER, SCISSORS = 0.1, 0.5, 0.9
WORDS = {
    "rock": ["rock", "stone", "fist"],
    "paper": ["paper", "flat hand", "open hand"],
    "scissors": ["scissors", "scissor", "cut"],
}
Fixtures = tuple[LoadedConfig, DialogueContent, Path]


@pytest.fixture
def fx(dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path) -> Fixtures:
    return dev_config, dialogue_content, tmp_path


async def rps_table(fx: Fixtures, robot: list[float], **kw: Any) -> GameTable:
    loaded, content, tmp_path = fx
    table = await make_game_table(loaded, content, tmp_path, rng=ScriptedRng(randoms=robot), **kw)
    base = load_game_setup(loaded.app.games)
    config = base.config.model_copy(update={"between_rounds_s": 0})
    setup = GameSetup(config, base.motions, build_registry(config))
    table.s.ctl.ctx.games = setup
    table.ctx.config = setup.config
    table.s.ctl.registry = setup.registry
    return table


def results(table: GameTable) -> list[tuple[str, str | None, str | None]]:
    return [(r["result"], r["inputs"]["you"], r["inputs"]["me"]) for r in table.rounds()]


# --- the rules (pure) ------------------------------------------------------------------------


def test_who_beats_whom() -> None:
    assert judge("paper", "rock") == "participant"
    assert judge("rock", "paper") == "robot"
    assert judge("scissors", "paper") == "participant"
    assert judge("rock", "rock") is None


@pytest.mark.parametrize(
    ("said", "choice"),
    [
        ("paper", "paper"),
        ("I'll go with a stone", "rock"),
        ("Scissors!", "scissors"),
        ("flat hand", "paper"),
        ("banana", None),
        ("rock or paper", None),  # two different choices: unclear
    ],
)
def test_the_spoken_choice_is_understood(said: str, choice: str | None) -> None:
    assert parse_choice(said, WORDS) == choice


# --- whole games -------------------------------------------------------------------------------


async def test_the_participant_wins_two_rounds_and_the_game(fx: Fixtures) -> None:
    table = await rps_table(fx, [ROCK, ROCK], script=["paper", "paper"])

    outcome = await table.play(GAME)

    assert outcome.result == "completed" and outcome.rounds == 2  # best of 3: decided at 2-0
    assert results(table) == [("participant_won", "paper", "rock")] * 2
    assert "rps_final_you" in table.s.pipi_lines()


async def test_the_robot_can_win_too(fx: Fixtures) -> None:
    table = await rps_table(fx, [PAPER, PAPER], script=["rock", "rock"])

    await table.play(GAME)

    assert results(table) == [("robot_won", "rock", "paper")] * 2
    assert "rps_final_robot" in table.s.pipi_lines()


async def test_a_draw_gives_no_point(fx: Fixtures) -> None:
    table = await rps_table(fx, [ROCK, ROCK, ROCK], script=["rock", "paper", "paper"])

    await table.play(GAME)

    assert [r[0] for r in results(table)] == ["draw", "participant_won", "participant_won"]
    assert "rps_draw" in table.s.pipi_lines()


async def test_an_unclear_answer_gets_one_question(fx: Fixtures) -> None:
    table = await rps_table(fx, [ROCK, ROCK], script=["banana", "scissors", "paper"])

    await table.play(GAME)

    assert "rps_unclear" in table.s.pipi_lines()
    assert results(table)[0] == ("robot_won", "scissors", "rock")


async def test_silence_means_the_round_does_not_count(fx: Fixtures) -> None:
    table = await rps_table(fx, [ROCK], script=[None, None])

    await table.play(GAME)

    first = table.rounds()[0]
    assert first["result"] == "no_contest" and first["inputs"]["you"] is None
    assert "rps_no_answer" in table.s.pipi_lines()


async def test_the_robot_counts_down_shows_its_choice_and_lets_go_of_it(fx: Fixtures) -> None:
    table = await rps_table(fx, [SCISSORS, SCISSORS], script=["rock", "rock"])

    await table.play(GAME)

    motions = [arg for kind, arg in table.robot_did("motion")]
    # (the rules come first, with an "excited" gesture)
    first_round = motions[motions.index("rps_shake") : motions.index("rps_scissors") + 2]
    assert first_round[:3] == ["rps_shake"] * 3
    assert first_round[3:] == ["rps_scissors", "idle"]  # the held choice is ended


async def test_camera_mode_is_not_built_yet_so_it_plays_by_voice(fx: Fixtures) -> None:
    table = await rps_table(fx, [ROCK, ROCK], script=["paper", "paper"])

    await table.play(GAME)

    start = table.s.data("game_start")[0]
    assert start["mode"] == "voice"
    fallback = table.s.data("game_fallback")
    assert fallback and fallback[0]["to"] == "voice"  # games.yaml says mode: camera
