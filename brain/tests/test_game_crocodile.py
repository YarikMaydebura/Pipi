"""Crocodile (the robot acts, the participant guesses): every path of a round.

Played on the real session game context with a fake robot body, fake LLM / STT and virtual
time. ``ScriptedRng.choice`` picks the first unused word, so the word order is known:
bird, boxer, swimmer, ...
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.games.config import CrocodileWord, load_games_config
from pipi_brain.games.crocodile import (
    CrocodileRobot,
    build_judge_messages,
    build_pick_messages,
    judge_by_keywords,
    mentions,
)
from pipi_brain.games.setup import GameSetup, build_registry, load_game_setup
from pipi_brain.speech.base import Utterance

from .conftest import CONFIG_DIR
from .session_harness import GameTable, make_game_table

Fixtures = tuple[LoadedConfig, DialogueContent, Path]
GAME = "crocodile_robot"
BIRD = CrocodileWord(
    word="bird", motion="act_bird", synonyms=("eagle", "flying"), close=("plane", "bat")
)


@pytest.fixture
def fx(dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path) -> Fixtures:
    return dev_config, dialogue_content, tmp_path


def verdict(correct: bool, close: bool = False) -> str:
    return json.dumps({"correct": correct, "close": close, "say": "hmm"})


def pick(word: str) -> str:
    return json.dumps({"word": word})


def setup_with(loaded: LoadedConfig, **crocodile: Any) -> GameSetup:
    """The real games.yaml with some crocodile values replaced (one round unless said)."""
    base = load_game_setup(loaded.app.games)
    values = {"rounds_study": 1, "llm_picks_word": False, **crocodile}
    config = base.config.model_copy(
        update={"crocodile": base.config.crocodile.model_copy(update=values)}
    )
    return GameSetup(config, base.motions, build_registry(config))


async def table_for(
    fx: Fixtures, *, crocodile: dict[str, Any] | None = None, **kw: Any
) -> GameTable:
    loaded, content, tmp_path = fx
    table = await make_game_table(loaded, content, tmp_path, **kw)
    setup = setup_with(loaded, **(crocodile or {}))
    table.s.ctl.ctx.games = setup  # the session context reads games from here
    table.ctx.config = setup.config
    table.s.ctl.registry = setup.registry
    return table


def acting_calls(table: GameTable) -> list[tuple[str, object]]:
    """Everything the robot did while acting: from the first acting motion until the
    reaction starts (happy eyes + celebrate, or the shrug of the reveal)."""
    calls = table.robot_did()
    start = calls.index(("motion", "act_bird"))
    reaction = (("eyes", "happy"), ("motion", "shrug"))
    end = next(i for i, call in enumerate(calls) if i > start and call in reaction)
    assert calls[end + 1][0] in ("motion", "speak")  # the reaction follows directly
    return calls[start:end]


# --- pure helpers ------------------------------------------------------------------------------


def test_keyword_judge() -> None:
    assert judge_by_keywords("is it a bird?", BIRD) == (True, False)
    assert judge_by_keywords("Birds!", BIRD) == (True, False)
    assert judge_by_keywords("an eagle maybe", BIRD) == (True, False)
    assert judge_by_keywords("a plane", BIRD) == (False, True)
    assert judge_by_keywords("a fish", BIRD) == (False, False)
    assert judge_by_keywords("birdhouse", BIRD) == (False, False)  # whole words only
    # the word is there, but it is not the guess: never correct by keyword
    assert judge_by_keywords("it's not a bird", BIRD) == (False, False)
    assert judge_by_keywords("that isn't an eagle, right?", BIRD) == (False, False)
    assert judge_by_keywords("no bird", BIRD) == (False, False)
    assert judge_by_keywords("is it a bird?", BIRD) == (True, False)  # a question is a guess
    assert mentions("two BOXERS", "boxer") and not mentions("boxing", "box")


def test_prompts_name_the_target_only_to_the_judge() -> None:
    system = build_judge_messages(BIRD, "a seagull")[0]["content"]
    assert '"bird"' in system and "eagle, flying" in system and '"correct"' in system
    pick_prompt = build_pick_messages([BIRD], ["football"])[0]["content"]
    assert "['bird']" in pick_prompt and "football" in pick_prompt


def test_rounds_per_mode_and_words_only_from_the_list() -> None:
    config = load_games_config(CONFIG_DIR / "games.yaml").crocodile
    game = CrocodileRobot(config)
    assert game.rounds("study") == 2 and game.rounds("dev") == 2
    assert game.rounds("demo") == config.rounds_demo > 2
    assert {w.motion for w in config.words} <= game.motions()
    assert game.requires == {"motions", "acting_motions"} and not game.has_fallback


# --- one round ---------------------------------------------------------------------------------


async def test_correct_guess_is_celebrated_and_remembered(fx: Fixtures) -> None:
    table = await table_for(fx, script=[("is it a bird?", 4)])
    outcome = await table.play(GAME)
    assert (outcome.result, outcome.rounds) == ("completed", 1)
    assert table.s.pipi_lines() == ["crocodile_rules", "crocodile_watch", "crocodile_correct"]
    assert table.s.pipi_said()[-1] == "Yes! I was a bird! Well guessed!"
    moves = table.robot_did("motion", "eyes")
    assert moves[:3] == [("motion", "excited"), ("eyes", "determined"), ("motion", "act_bird")]
    assert moves[-2:] == [("eyes", "happy"), ("motion", "celebrate")]
    (round_,) = table.rounds()
    assert round_["result"] == "guessed" and round_["winner"] == "participant"
    assert round_["inputs"]["word"] == "bird" and round_["inputs"]["word_pick"] == "random"
    assert round_["inputs"]["guesses"] == [
        {
            "text": "is it a bird?",
            "correct": True,
            "close": False,
            "method": "keyword",
            "at_ms": 4000,
        }
    ]
    assert round_["timings"]["acting_ms"] == 4000
    assert table.s.chat.calls == []  # exact match: no LLM needed
    events = table.s.ctl.state.memory.game_events
    assert [(e.game, e.summary) for e in events] == [
        (GAME, "You guessed that I was a bird on the first try!")
    ]


async def test_llm_judges_synonyms_and_close_guesses(fx: Fixtures) -> None:
    table = await table_for(
        fx,
        script=[("a pterodactyl", 2), ("a seagull", 2)],
        llm=[verdict(False, close=True), verdict(True)],
    )
    await table.play(GAME)
    guesses = table.rounds()[0]["inputs"]["guesses"]
    assert [(g["correct"], g["close"], g["method"]) for g in guesses] == [
        (False, True, "llm"),
        (True, False, "llm"),
    ]
    acting = acting_calls(table)
    assert ("motion", "nod") in acting  # encouraging gesture for "close"
    assert ("eyes", "thinking") in acting  # feedback while the LLM judges
    assert table.s.ctl.state.memory.game_events[0].summary.endswith("after 2 tries!")
    judge_prompt = table.s.chat.calls[0][0]["content"]
    assert "charades" in judge_prompt and table.s.chat.calls[0][1]["content"] == "a pterodactyl"


async def test_hint_after_two_wrong_and_reveal_after_three(fx: Fixtures) -> None:
    table = await table_for(
        fx,
        script=[("a fish", 1), ("a tree", 1), ("a car", 1)],
        llm=[verdict(False), verdict(False), verdict(False)],
    )
    await table.play(GAME)
    (round_,) = table.rounds()
    assert round_["result"] == "revealed" and round_["winner"] is None
    assert round_["inputs"]["reveal_reason"] == "max_wrong_guesses"
    assert round_["inputs"]["wrong_guesses"] == 3 and round_["inputs"]["hint_given"] is True
    motions = [arg for kind, arg in acting_calls(table) if kind == "motion"]
    # act; wrong -> head shake, act again; wrong -> head shake, the hint (stand still, then
    # the motion from its start); the third wrong guess -> reveal
    assert motions == ["act_bird", "shake_head", "act_bird", "shake_head", "idle", "act_bird"]
    eyes = [arg for kind, arg in acting_calls(table) if kind == "eyes"]
    assert eyes.count("surprised") == 1  # the "look!" of the hint
    assert table.s.pipi_lines()[-1] == "crocodile_reveal"
    assert table.s.pipi_said()[-1] == "Ooh, tricky one! I was a bird!"
    assert ("motion", "shrug") in table.robot_did("motion")
    assert table.s.ctl.state.memory.game_events[0].summary == (
        "You could not guess that I was a bird, so I had to tell you."
    )


async def test_llm_failure_falls_back_to_the_keyword_lists(fx: Fixtures) -> None:
    table = await table_for(
        fx,
        script=[("a plane?", 1), ("no idea", 1), ("an eagle", 1)],
        llm=[RuntimeError("down"), "{ not json"],
        crocodile={"keyword_shortcut": False},
    )
    table.s.chat.default = "also not json"  # every later LLM answer is invalid too
    await table.play(GAME)
    guesses = table.rounds()[0]["inputs"]["guesses"]
    assert [(g["correct"], g["close"], g["method"]) for g in guesses] == [
        (False, True, "keyword_fallback"),  # "plane" is in bird's close list
        (False, False, "keyword_fallback"),
        (True, False, "keyword_fallback"),  # synonym, decided without the LLM
    ]
    errors = table.s.data("llm_error")
    assert len(errors) == 3 and {e["purpose"] for e in errors} == {"guess_judge"}
    assert all(e["fallback"] is True for e in errors)
    assert table.rounds()[0]["result"] == "guessed"


async def test_a_negated_guess_goes_to_the_llm_instead_of_the_shortcut(fx: Fixtures) -> None:
    table = await table_for(
        fx, script=[("it's not a bird, is it?", 1), ("a bird", 1)], llm=[verdict(False)]
    )
    await table.play(GAME)
    guesses = table.rounds()[0]["inputs"]["guesses"]
    assert [(g["correct"], g["method"]) for g in guesses] == [(False, "llm"), (True, "keyword")]


async def test_keyword_shortcut_can_be_switched_off(fx: Fixtures) -> None:
    table = await table_for(
        fx, script=[("a bird", 1)], llm=[verdict(True)], crocodile={"keyword_shortcut": False}
    )
    await table.play(GAME)
    assert table.rounds()[0]["inputs"]["guesses"][0]["method"] == "llm"
    assert len(table.s.chat.calls) == 1


async def test_reveal_after_thirty_seconds_with_the_motion_repeated(fx: Fixtures) -> None:
    table = await table_for(fx)  # the participant never says anything
    await table.play(GAME)
    (round_,) = table.rounds()
    assert round_["result"] == "revealed" and round_["inputs"]["reveal_reason"] == "timeout"
    assert round_["timings"]["acting_ms"] == 30_000
    assert round_["inputs"]["motion_repeats"] == 4  # at 6, 12, 18 and 24 s
    motions = [arg for kind, arg in acting_calls(table) if kind == "motion"]
    assert motions == ["act_bird"] * 5
    assert round_["inputs"]["guesses"] == [] and round_["inputs"]["hint_given"] is False


async def test_pipi_never_speaks_while_acting(fx: Fixtures) -> None:
    """The hard rule: from the first acting motion to the reveal, not one word."""
    unclear = Utterance(np.zeros(1600, dtype=np.float32), 16000, 0.0, 0.1, False)
    table = await table_for(
        fx,
        voice=True,
        script=[(unclear, 2), (unclear, 2), ("a fish", 2), ("a tree", 2), ("a car", 2)],
        llm=[verdict(False), verdict(False, close=True), verdict(False)],
    )
    table.s.stt.answers = ["", RuntimeError("stt down")]  # empty transcript, then a failure
    spoken_before = len(table.s.tts.texts)
    await table.play(GAME)
    acting = acting_calls(table)
    assert [call for call in acting if call[0] in ("speak", "caption")] == []
    assert len(acting) > 8  # eyes and motions kept going the whole time
    # no "could you say that again?" and no re-prompt during the round either
    lines = table.s.pipi_lines()
    assert lines == ["crocodile_rules", "crocodile_watch", "crocodile_reveal"]
    assert len(table.s.tts.texts) - spoken_before == 3
    assert table.s.data("game_rule_blocked") == []  # the game itself never even tried
    assert len(table.s.data("stt_error")) == 1 and table.s.data("clarification")
    assert table.rounds()[0]["inputs"]["wrong_guesses"] == 3  # unclear sounds are not guesses


async def test_a_pause_freezes_the_round_timer(fx: Fixtures) -> None:
    table = await table_for(fx, script=[("a bird", 20)])
    pause = table.s.ctl.pause

    async def pause_for_a_minute() -> None:
        await table.s.clock.sleep(10)
        pause.pause()
        await table.s.clock.sleep(60)
        pause.resume()

    await table.play(GAME, pause_for_a_minute())
    (round_,) = table.rounds()
    assert round_["result"] == "guessed"  # 80 s of clock time, but only 20 s of game time
    assert round_["timings"]["acting_ms"] == 20_000


async def test_motion_failure_ends_the_game_politely(fx: Fixtures) -> None:
    table = await table_for(fx)
    table.s.robot.connected = False  # the body went away: the motion cannot be played
    outcome = await table.play(GAME)
    assert (outcome.result, outcome.rounds) == ("aborted", 1)
    assert table.rounds()[0]["result"] == "motion_failed"
    assert table.s.pipi_lines()[-1] == "game_motion_failed"
    assert table.s.ctl.state.memory.game_events == ()


# --- the word ----------------------------------------------------------------------------------


async def test_words_never_repeat_in_a_session(fx: Fixtures) -> None:
    table = await table_for(fx, crocodile={"round_timeout_s": 1, "rounds_study": 3})
    game = table.s.ctl.registry.implementation(GAME)
    assert game is not None
    all_words = [w.word for w in table.ctx.config.crocodile.words]
    acted: list[str] = []
    while game.can_play():
        await table.play(GAME)
        acted = [r["inputs"]["word"] for r in table.rounds()]
    assert sorted(acted) == sorted(all_words) and len(set(acted)) == len(all_words) == 8
    assert game.rounds("study") == 1  # nothing left, but never zero rounds
    outcome = await table.play(GAME)  # the WoZ starts it anyway: Pipi says it cannot
    assert outcome.result == "unavailable"
    assert table.s.ctl.registry.available(table.ctx.capabilities) == (
        table.s.ctl.registry.implementation("quick_draw"),
    )


async def test_llm_picks_among_the_unused_words_only(fx: Fixtures) -> None:
    table = await table_for(
        fx,
        crocodile={"llm_picks_word": True, "round_timeout_s": 1, "rounds_study": 3},
        llm=[pick("Drummer"), pick("unicorn"), pick("drummer")],
    )
    table.ctx.remember("chat", "x")  # memory exists; interests go into the prompt
    await table.play(GAME)
    rounds = table.rounds()
    assert [(r["inputs"]["word"], r["inputs"]["word_pick"]) for r in rounds] == [
        ("drummer", "llm"),
        ("bird", "random"),  # "unicorn" is not in the list -> random fallback
        ("boxer", "random"),  # "drummer" was used already -> not allowed again
    ]
    errors = [e for e in table.s.data("llm_error") if e["purpose"] == "crocodile_word"]
    assert len(errors) == 2 and "unicorn" in errors[0]["error"]
    prompt = table.s.chat.calls[0][0]["content"]
    assert "'bird'" in prompt and "Choose exactly ONE word" in prompt
    # the word is never spoken before the reveal: the pick ran during the intro line
    assert table.s.pipi_lines()[:2] == ["crocodile_rules", "crocodile_watch"]
