"""Games inside the real session: study and demo flow, the voice menu, WoZ control, and the
game moments that reach the goodbye and RETURN lines.

Sessions start with a WoZ ``goto_phase`` into the break, so the scripts only contain what the
participant says during the games. The harness is a typed session: in the duel, a typed line
is the bang. ``ScriptedRng`` defaults: 3.5 s before green, the robot lets the participant
win, Crocodile words in list order (bird, boxer, ...).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent

from .session_harness import Session, make_session, turn

Fixtures = tuple[LoadedConfig, DialogueContent, Path]
MENU_QUESTION = "What do you want to play next: Crocodile, a duel or a staring contest?"
BIRD_MOMENT = "You guessed that I was a bird on the first try!"
DUEL_MOMENT = "You beat me in the quick-draw duel, 2 to 0!"
# Crocodile: bird in round 1, boxer in round 2 (the second answer comes after the 2.5 s
# listening window between the rounds). Duel: Enter 0.5 s after green, twice.
CROCODILE_TWO_ROUNDS: list[object] = [("a bird", 3), ("boxer!", 5)]
DUEL_TWO_WINS: list[object] = [("", 4.0), ("", 6.5)]


@pytest.fixture
def fx(dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path) -> Fixtures:
    return dev_config, dialogue_content, tmp_path


def intent(action: str, game: str | None = None) -> str:
    return json.dumps({"action": action, "game": game})


def pick(word: str) -> str:
    return json.dumps({"word": word})


async def run_from(s: Session, phase: str, *, until: str | None = None) -> None:
    """Jump into ``phase`` with the WoZ and run to the end (or end the session at ``until``)."""
    task = s.start()
    assert (await s.woz("goto_phase", phase=phase)).ok
    if until is not None:
        await s.until_phase(until)
        await s.woz("end_session")
    await task


def games_played(s: Session) -> list[tuple[str, str]]:
    return [(d["game"], d["result"]) for d in s.data("game_end")]


def system_prompt(s: Session, phase: str) -> str:
    """The system prompt of the dialogue turn Pipi was asked for in ``phase``."""
    return next(
        call[0]["content"]
        for call in s.chat.calls
        if f"Current phase: {phase}" in call[0]["content"]
    )


# --- study mode: Crocodile first (2 rounds), then ONE chosen game ---


async def test_study_flow_crocodile_then_one_chosen_game(fx: Fixtures) -> None:
    s = make_session(
        *fx,
        mode="study",
        script=[*CROCODILE_TWO_ROUNDS, "the cowboy one", *DUEL_TWO_WINS],
        llm=[
            pick("bird"),
            pick("boxer"),
            intent("start_game", "quick_draw"),
            turn("You beat me twice! Back to your text, see you on the screen!"),
            turn("I'm back! You guessed my bird so fast. Now finish those questions!"),
        ],
    )
    await run_from(s, "GAME_CROCODILE")
    assert s.phases() == [
        "MIGRATE_OUT",
        "GAME_CROCODILE",
        "GAME_MENU",
        "GAME_CHOSEN",
        "ROBOT_GOODBYE",  # study: no second chosen game
        "MIGRATE_IN",
        "RETURN",
        "END",
    ]
    assert games_played(s) == [("crocodile_robot", "completed"), ("quick_draw", "completed")]
    rounds = s.data("game_round")
    assert [(r["game"], r["round"], r["result"]) for r in rounds] == [
        ("crocodile_robot", 1, "guessed"),
        ("crocodile_robot", 2, "guessed"),
        ("quick_draw", 1, "participant_won"),
        ("quick_draw", 2, "participant_won"),
    ]
    for round_ in rounds:  # every round: inputs, result, timings, fallback (the study data)
        assert {
            "game",
            "round",
            "mode",
            "result",
            "winner",
            "inputs",
            "timings",
            "fallback",
        } <= set(round_)
        assert round_["timings"]["round_ms"] > 0
    assert [r["inputs"]["word_pick"] for r in rounds[:2]] == ["llm", "llm"]
    assert rounds[2]["timings"]["participant_reaction_ms"] == 500
    assert rounds[2]["fallback"] == "typed"
    # the phase and the body of every game event are the robot's
    for event in s.events("game_round"):
        assert event["body"] == "fake_robot" and event["phase"].startswith("GAME_")
    assert s.data("game_choice") == [
        {"heard": "the cowboy one", "game": "quick_draw", "method": "llm"}
    ]
    assert MENU_QUESTION in s.pipi_said() and "Okay, a duel it is!" in s.pipi_said()
    memory = s.ctl.state.memory
    assert [(e.game, e.summary) for e in memory.game_events] == [
        ("crocodile_robot", BIRD_MOMENT),
        ("crocodile_robot", "You guessed that I was a boxer on the first try!"),
        ("quick_draw", DUEL_MOMENT),
    ]
    assert memory.break_highlight == BIRD_MOMENT
    saved = json.loads((s.logger.folder / "memory.json").read_text("utf-8"))
    assert len(saved["game_events"]) == 3
    assert s.ctl.snapshot().memory_summary["games"].count("quick_draw") == 1


async def test_game_moments_reach_the_goodbye_and_the_return_prompts(fx: Fixtures) -> None:
    goodbye = "You beat me twice! Back to your text, see you on the screen!"
    s = make_session(
        *fx,
        script=[*CROCODILE_TWO_ROUNDS, "the cowboy one", *DUEL_TWO_WINS],
        llm=[pick("bird"), pick("boxer"), intent("start_game", "quick_draw"), turn(goodbye)],
    )
    await run_from(s, "GAME_CROCODILE")
    goodbye_prompt = system_prompt(s, "ROBOT_GOODBYE")
    assert f'A game moment from this break to mention, in your own words: "{DUEL_MOMENT}"' in (
        goodbye_prompt
    )
    goodbye_call = next(c for c in s.chat.calls if "ROBOT_GOODBYE" in c[0]["content"])
    assert "Break moments:" in goodbye_call[1]["content"]  # the memory block has all of them
    assert BIRD_MOMENT in goodbye_call[1]["content"] and DUEL_MOMENT in goodbye_call[1]["content"]
    return_prompt = system_prompt(s, "RETURN")
    assert f'When you left your robot body you said: "{goodbye}"' in return_prompt
    assert "Recall a DIFFERENT detail now." in return_prompt
    assert f'Another game moment you can mention, in your own words: "{BIRD_MOMENT}"' in (
        return_prompt
    )
    references = s.data("memory_reference")
    assert {"what": ["game_events"], "body": "fake_robot"} in references  # the goodbye
    assert references[-1]["body"] == "desktop_pet"  # RETURN, back on the screen


async def test_fallback_lines_carry_the_game_moment_when_the_llm_fails(fx: Fixtures) -> None:
    s = make_session(*fx, script=[*CROCODILE_TWO_ROUNDS, "the cowboy one", *DUEL_TWO_WINS])
    s.chat.default = "{ broken"  # every LLM answer of this session is invalid
    await run_from(s, "GAME_CROCODILE")
    said = s.pipi_said()
    assert f"{DUEL_MOMENT} Okay, back to your text. See you on the screen!" in said
    assert f"I'm back on your screen! {BIRD_MOMENT} Good luck with the questions." in said
    lines = s.pipi_lines()
    assert "robot_goodbye_game" in lines and "return_fallback_game" in lines
    # ... and the games themselves ran on their fallbacks
    assert [r["inputs"]["word_pick"] for r in s.data("game_round")[:2]] == ["random", "random"]
    assert s.data("game_choice")[0]["method"] == "keyword"
    purposes = {e.get("purpose") for e in s.data("llm_error")}
    assert {"crocodile_word", "game_intent"} <= purposes


async def test_no_game_moment_without_the_memory_cue(fx: Fixtures) -> None:
    s = make_session(
        *fx,
        script=[*CROCODILE_TWO_ROUNDS, "the cowboy one", *DUEL_TWO_WINS],
        cues={"memory_references": False},
    )
    s.chat.default = "{ broken"
    await run_from(s, "GAME_CROCODILE")
    lines = s.pipi_lines()
    assert "robot_goodbye" in lines and "return_fallback" in lines
    assert "robot_goodbye_game" not in lines and "return_fallback_game" not in lines
    assert s.data("memory_reference") == []


async def test_only_one_game_moment_gives_return_the_plain_line(fx: Fixtures) -> None:
    s = make_session(*fx, script=["duel", *DUEL_TWO_WINS])
    s.chat.default = "{ broken"
    await run_from(s, "GAME_MENU")
    said = s.pipi_said()
    assert f"{DUEL_MOMENT} Okay, back to your text. See you on the screen!" in said
    assert "return_fallback" in s.pipi_lines()  # nothing different to recall


# --- demo mode: any game first, loop until "done" ---


async def test_demo_flow_loops_until_the_participant_is_done(fx: Fixtures) -> None:
    s = make_session(
        *fx,
        mode="demo",
        session={"game_loop": True, "first_game": None, "chat_max_s": 60},
        script=[
            None,  # CHAT: silent ...
            None,  # ... also after the re-prompt
            "charades please",
            ("a bird", 2),
            ("another game", 1),  # between the rounds of Crocodile
            "again",  # menu: the game just played
            ("boxer", 2),
            ("let's do the duel", 1),  # names the next game: no menu in between
            ("I'm done", 18),  # nobody shoots in the duel; this is the answer to the menu after it
        ],
    )
    await run_from(s, "CHAT")
    phases = s.phases()
    assert phases[:3] == ["MIGRATE_OUT", "CHAT", "GAME_MENU"]  # no fixed first game in demo
    assert "GAME_CROCODILE" not in phases
    assert phases[3:] == [
        "GAME_CHOSEN",  # Crocodile
        "GAME_MENU",  # "another game"
        "GAME_CHOSEN",  # "again" = Crocodile
        "GAME_CHOSEN",  # "let's do the duel"
        "GAME_MENU",  # the loop
        "ROBOT_GOODBYE",  # "I'm done"
        "MIGRATE_IN",
        "RETURN",
        "END",
    ]
    assert games_played(s) == [
        ("crocodile_robot", "another_game"),
        ("crocodile_robot", "another_game"),
        ("quick_draw", "completed"),
    ]
    assert s.data("game_start")[0]["rounds_planned"] == 3  # more rounds in demo
    words = [r["inputs"]["word"] for r in s.data("game_round") if r["game"] == "crocodile_robot"]
    assert words == ["bird", "boxer"]  # no repeat across the two games
    choices = [(c["heard"], c["game"], c.get("action"), c["method"]) for c in s.data("game_choice")]
    assert choices == [
        ("charades please", "crocodile_robot", None, "keyword"),
        ("another game", None, "another_game", "keyword"),  # no game named: the menu asks
        ("again", "crocodile_robot", None, "keyword"),
        ("let's do the duel", "quick_draw", "another_game", "keyword"),
        ("I'm done", None, "stop", "keyword"),
    ]
    assert [r["inputs"]["reason"] for r in s.data("game_round")[2:]] == ["too_slow", "too_slow"]


# --- the voice menu ---


async def menu(fx: Fixtures, script: list[object], llm: list[object] | None = None) -> Session:
    s = make_session(*fx, script=script, llm=llm)
    await run_from(s, "GAME_MENU", until="GAME_CHOSEN")
    return s


async def test_menu_offers_only_built_games_and_uses_the_llm_intent(fx: Fixtures) -> None:
    s = await menu(fx, ["the one where you act"], [intent("start_game", "crocodile_robot")])
    assert MENU_QUESTION in s.pipi_said()
    assert not any("rock" in text for text in s.pipi_said())  # rps_arms is not built yet
    assert s.data("game_choice") == [
        {"heard": "the one where you act", "game": "crocodile_robot", "method": "llm"}
    ]
    assert "Okay, Crocodile it is!" in s.pipi_said()
    assert s.data("game_start")[0]["game"] == "crocodile_robot"
    prompt = s.chat.calls[0][0]["content"]
    assert "quick_draw: the quick-draw duel" in prompt and "ONLY valid JSON" in prompt


async def test_menu_keyword_fallback_when_the_llm_fails(fx: Fixtures) -> None:
    s = await menu(fx, ["the cowboy one"], [RuntimeError("no network")])
    assert s.data("game_choice") == [
        {"heard": "the cowboy one", "game": "quick_draw", "method": "keyword"}
    ]
    error = s.data("llm_error")[0]
    assert error["purpose"] == "game_intent" and error["fallback"] is True


async def test_menu_explains_a_game_it_cannot_play_yet(fx: Fixtures) -> None:
    s = await menu(
        fx, ["rock paper scissors", "okay, the duel"], [intent("start_game", "rps_arms"), "{"]
    )
    assert (
        "I can't play that one yet. How about Crocodile, a duel or a staring contest?"
        in s.pipi_said()
    )
    first, second = s.data("game_choice")
    assert first == {
        "heard": "rock paper scissors",
        "game": "rps_arms",
        "method": "llm",
        "available": False,
    }
    assert (second["game"], second["method"]) == ("quick_draw", "keyword")


async def test_menu_one_clarifying_question_then_the_default_game(fx: Fixtures) -> None:
    s = await menu(fx, ["hmm", "I don't know"], [intent("clarify"), intent("unknown")])
    assert "Sorry, which game: Crocodile, a duel or a staring contest?" in s.pipi_said()
    assert "Let's do a duel then!" in s.pipi_said()
    assert s.data("clarification") == [{"reason": "unclear_intent"}] * 2
    assert s.data("game_choice") == [
        {"heard": "I don't know", "game": "quick_draw", "method": "default"}
    ]
    assert s.data("game_start")[0]["game"] == "quick_draw"


async def test_menu_silence_picks_the_default_game(fx: Fixtures) -> None:
    s = await menu(fx, [])
    assert s.data("game_choice") == [{"heard": None, "game": "quick_draw", "method": "default"}]
    change = next(c for c in s.data("phase_change") if c["to"] == "GAME_CHOSEN")
    assert change["trigger"] == "timer"
    assert s.data("silence_reprompt")[-1] == {"waited_s": 10, "action": "default"}


async def test_menu_lists_the_games_on_request(fx: Fixtures) -> None:
    s = await menu(
        fx,
        ["which games are there?", "crocodile"],
        [intent("list_games"), intent("start_game", "crocodile_robot")],
    )
    assert "I can play Crocodile, a duel or a staring contest. Which one?" in s.pipi_said()
    assert s.data("clarification") == []  # asking for the list is not a failure
    assert s.data("game_choice")[0]["game"] == "crocodile_robot"


async def test_menu_stop_goes_to_the_goodbye(fx: Fixtures) -> None:
    s = make_session(*fx, script=["no more games please"], llm=[intent("stop")])
    await run_from(s, "GAME_MENU")
    assert s.phases()[:3] == ["MIGRATE_OUT", "GAME_MENU", "ROBOT_GOODBYE"]
    assert s.data("game_choice") == [
        {"heard": "no more games please", "game": None, "method": "llm", "action": "stop"}
    ]
    assert s.data("game_start") == []
    change = next(c for c in s.data("phase_change") if c["to"] == "ROBOT_GOODBYE")
    assert change["trigger"] == "user"


# --- "stop" / "another game" between rounds, through the phases ---


async def test_stop_between_rounds_ends_the_games(fx: Fixtures) -> None:
    s = make_session(*fx, script=[("a bird", 2), ("stop please", 1)])
    await run_from(s, "GAME_CROCODILE")
    assert s.phases()[:3] == ["MIGRATE_OUT", "GAME_CROCODILE", "ROBOT_GOODBYE"]
    assert games_played(s) == [("crocodile_robot", "stopped")]
    assert "Okay, no more games!" in s.pipi_said()


async def test_another_game_in_the_first_game_goes_to_the_menu(fx: Fixtures) -> None:
    s = make_session(*fx, script=[("a bird", 2), ("something else", 1), "duel"])
    await run_from(s, "GAME_CROCODILE", until="GAME_CHOSEN")
    assert s.phases()[:4] == ["MIGRATE_OUT", "GAME_CROCODILE", "GAME_MENU", "GAME_CHOSEN"]
    assert s.data("game_start")[-1]["game"] == "quick_draw"


async def test_study_mode_plays_only_one_chosen_game(fx: Fixtures) -> None:
    """ "Another game" during the chosen game does not open the menu again in study mode."""
    s = make_session(*fx, mode="study", script=["crocodile", ("a bird", 2), ("another game", 1)])
    await run_from(s, "GAME_MENU")
    assert s.phases()[:4] == ["MIGRATE_OUT", "GAME_MENU", "GAME_CHOSEN", "ROBOT_GOODBYE"]
    assert games_played(s) == [("crocodile_robot", "another_game")]


# --- robot missing: the break runs on the screen ---


async def test_on_the_pet_crocodile_is_skipped_and_duel_or_staring_is_offered(
    fx: Fixtures,
) -> None:
    s = make_session(*fx, robot_connected=False, script=["the duel"])
    await run_from(s, "GAME_CROCODILE", until="GAME_CHOSEN")
    # The pet has no acting motions: Pipi says so instead of standing still for 30 seconds.
    start, end = s.data("game_start")[0], s.data("game_end")[0]
    assert start["missing_requirements"] == ["acting_motions"] and end["result"] == "unavailable"
    assert "game_unavailable_now" in s.pipi_lines()
    # both have a no-body variant: the duel (typed / slow motion), staring (pretend mode)
    assert "What do you want to play next: a duel or a staring contest?" in s.pipi_said()
    assert s.data("game_choice") == [
        {"heard": "the duel", "game": "quick_draw", "method": "keyword"}
    ]
    assert s.robot.calls == [] and ("motion", "act_bird") not in s.pet.calls


# --- WoZ control of a running game ---


async def settle(s: Session, seconds: float) -> None:
    """Let the session run for ``seconds`` of virtual time."""
    target = s.clock.now() + seconds
    for _ in range(500_000):
        if s.clock.now() >= target:
            break
        await asyncio.sleep(0)
    for _ in range(300):
        await asyncio.sleep(0)


async def test_end_game_stops_crocodile_cleanly(fx: Fixtures) -> None:
    s = make_session(*fx, auto_start=False)
    task = s.start()
    await s.woz("goto_phase", phase="GAME_CROCODILE")
    await s.until_phase("GAME_CROCODILE")
    await settle(s, 8)  # in the middle of the acting step
    assert (await s.woz("end_game")).ok
    await s.until_phase("GAME_MENU")
    await s.woz("end_session")
    await task
    assert games_played(s) == [("crocodile_robot", "interrupted")]
    (round_,) = s.data("game_round")
    assert (round_["round"], round_["result"]) == (1, "interrupted")
    assert round_["inputs"]["word"] == "bird"  # what was going on is still in the log
    # the acting motion is held by the body: the brain tells it to rest
    acting = s.robot.calls.index(("motion", "act_bird"))
    assert ("motion", "idle") in s.robot.calls[acting:]
    assert ("eyes", "idle") in s.robot.calls[acting:]
    assert s.ctl.state.memory.game_events == ()


async def test_emergency_stop_during_the_duel_then_resume(fx: Fixtures) -> None:
    s = make_session(*fx, auto_start=False, bang=[None, None, None, None])
    task = s.start()
    await s.woz("goto_phase", phase="CHAT")
    await s.until_phase("CHAT")
    assert (await s.woz("start_game", game="crocodile_robot")).ok  # not the default game
    await s.until_phase("GAME_CHOSEN")
    await settle(s, 5)
    assert (await s.woz("emergency_stop", reason="technical_failure")).ok
    await settle(s, 0)
    assert ("stop", None) in s.robot.calls and ("stop", None) in s.pet.calls
    assert s.ctl.state.halted and s.ctl.ctx.woz_signals._waiters == []
    assert games_played(s) == [("crocodile_robot", "interrupted")]
    calls_when_stopped = len(s.robot.calls)
    await settle(s, 60)
    acted = [c for c in s.robot.calls[calls_when_stopped:] if c[0] in ("speak", "motion")]
    assert acted == []  # nothing goes on after the stop (not even the "rest" motion)
    assert (await s.woz("resume")).ok  # restarts the stopped phase: the SAME game again
    await settle(s, 3)
    assert [d["game"] for d in s.data("game_start")] == ["crocodile_robot", "crocodile_robot"]
    await s.woz("end_session")
    await task


async def test_emergency_stop_disarms_the_bang_detector(fx: Fixtures) -> None:
    s = make_session(*fx, auto_start=False, bang=[None])
    task = s.start()
    await s.woz("goto_phase", phase="CHAT")
    await s.until_phase("CHAT")
    await s.woz("start_game", game="quick_draw")
    await s.until_phase("GAME_CHOSEN")
    await settle(s, 2)  # eyes on countdown, the detector is armed
    assert s.bang is not None and s.bang.armed == 1
    assert ("eyes", "countdown") in s.robot.calls
    await s.woz("emergency_stop", reason="technical_failure")
    await settle(s, 30)
    assert s.ctl.ctx.woz_signals._waiters == [] and s.bang.armed == 1
    assert s.data("game_round")[0]["result"] == "interrupted"
    assert s.data("game_end")[0]["mode"] == "detector"
    await s.woz("end_session")
    await task


async def test_session_start_lists_the_games(fx: Fixtures) -> None:
    s = make_session(*fx, auto_start=False, bang=[])
    task = s.start()
    await s.woz("end_session")
    await task
    assert s.data("session_start")[0]["games"] == {
        "built": ["crocodile_robot", "quick_draw", "staring"],
        "first_game": "crocodile_robot",
        "default_game": "quick_draw",
        "good_sport": True,
        "bang_detector": True,
        "blink_detector": False,
    }


# --- typed sessions: just Enter ---


async def test_a_bare_enter_is_only_heard_by_the_duel(fx: Fixtures) -> None:
    """In a typed session Enter alone is the bang; every other phase ignores it."""
    s = make_session(*fx, script=["", "", "the calm one"])
    task = s.start()
    await s.until_phase("GREETING")
    await s.woz("end_session")
    await task
    assert s.data("persona_choice") == [{"persona": "calm", "method": "voice"}]
    user_turns = [d["text"] for d in s.data("turn") if d["speaker"] == "user"]
    assert user_turns == ["the calm one"]  # the empty lines were not "said"
    assert s.data("clarification") == []


async def test_terminal_input_passes_a_bare_enter_on_in_typed_mode() -> None:
    from pipi_brain.fakes import FakeTextInput
    from pipi_brain.phases.inputs import TerminalSessionInput, TypedLine

    commands: list[str] = []

    async def on_command(line: str) -> None:
        commands.append(line)

    source = TerminalSessionInput(
        audio_input=None,
        text_input=FakeTextInput(["", "  ", "/help", "bang"]),
        on_command=on_command,
        on_quit=lambda: None,
        log=lambda kind, data: None,
        alert=lambda level, message: None,
        emit=lambda text: None,
    )
    source.start()
    got = [await asyncio.wait_for(source.next_input(), 1) for _ in range(3)]
    assert got == [TypedLine(""), TypedLine(""), TypedLine("bang")]
    assert commands == ["/help"]
    await source.close()
