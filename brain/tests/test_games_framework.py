"""The game framework: registry, intent parsing, the round runner and the game context rules.

The runner tests use a tiny scripted game on the REAL session game context (fake bodies,
fake LLM, virtual clock), so logging, memory and the speech rules are the real code.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.dialogue.schemas import InvalidModelOutput
from pipi_brain.games.base import Game, GameContext, GameInfo, RoundResult
from pipi_brain.games.intent import (
    GameIntent,
    between_rounds,
    build_intent_messages,
    keyword_between,
    keyword_intent,
    parse_game_intent,
    understand,
    yes_or_no,
)
from pipi_brain.games.registry import KNOWN_GAMES, GameRegistry, game_info
from pipi_brain.games.runner import run_game
from pipi_brain.games.setup import build_registry, load_game_setup
from pipi_brain.phases.woz_signals import WozSignals

from .session_harness import GameTable, make_game_table

Fixtures = tuple[LoadedConfig, DialogueContent, Path]


@pytest.fixture
def fx(dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path) -> Fixtures:
    return dev_config, dialogue_content, tmp_path


def intent_json(action: str, game: str | None = None) -> str:
    return json.dumps({"action": action, "game": game, "say": "ok"})


class StubGame(Game):
    """A scripted game: each round returns the next prepared result."""

    info = GameInfo("stub", "the stub game", ("stub",), frozenset(), menu_phrase="a stub")

    def __init__(
        self,
        results: Sequence[RoundResult],
        *,
        requires: frozenset[str] = frozenset(),
        fallback_ok: bool = False,
        playable: bool = True,
        done_after: int | None = None,
    ) -> None:
        self.info = GameInfo("stub", "the stub game", ("stub",), requires, menu_phrase="a stub")
        self.has_fallback = fallback_ok  # type: ignore[misc]
        self.max_rounds = len(results)
        self._results = list(results)
        self._fallback_ok = fallback_ok
        self._playable = playable
        self._done_after = done_after
        self._variant = "normal"
        self.calls: list[str] = []
        self.block = asyncio.Event()  # set = rounds return at once
        self.block.set()

    @property
    def variant(self) -> str:
        return self._variant

    def can_play(self) -> bool:
        return self._playable

    def start(self, ctx: GameContext) -> None:
        self.calls.append("start")

    async def explain(self, ctx: GameContext) -> None:
        self.calls.append("explain")

    async def play_round(self, ctx: GameContext, round_no: int) -> RoundResult:
        self.calls.append(f"round{round_no}")
        await self.block.wait()
        await ctx.wait(4)  # a round takes 4 virtual seconds
        return self._results[round_no - 1]

    async def fallback_mode(self, ctx: GameContext) -> bool:
        self.calls.append("fallback")
        if self._fallback_ok:
            self._variant = "simple"
        return self._fallback_ok

    def finished(self, results: Sequence[RoundResult]) -> bool:
        return self._done_after is not None and len(results) >= self._done_after

    async def finish(self, ctx: GameContext, results: Sequence[RoundResult]) -> str | None:
        self.calls.append("finish")
        return "We played the stub game."


def win(memory: str | None = None) -> RoundResult:
    return RoundResult(
        "participant_won",
        inputs={"said": "x"},
        timings={"reaction_ms": 300},
        winner="participant",
        memory=memory,
    )


async def play(table: GameTable, game: Game) -> Any:
    registry = table.s.ctl.registry
    return await table.run(run_game(game, table.ctx, registry=registry))


# --- registry ----------------------------------------------------------------------------------


def test_registry_hides_games_that_cannot_be_played(dev_config: LoadedConfig) -> None:
    registry = build_registry(load_game_setup(dev_config.app.games).config)
    everything = frozenset({"speech", "motions", "acting_motions", "microphone", "bang_detector"})
    assert [g.id for g in registry.available(everything)] == [
        "crocodile_robot",
        "quick_draw",
        "staring",
        "rps_arms",
    ]
    # no acting motions on this body (the pet, or the real robot before M5): Crocodile has no
    # fallback -> hidden; the duel (typed / slow motion), the staring contest (pretend mode)
    # and rock-paper-scissors (voice mode) have one -> still offered
    on_the_pet = frozenset({"speech", "motions"})
    no_body = ["quick_draw", "staring", "rps_arms"]
    assert [g.id for g in registry.available(on_the_pet)] == no_body
    assert [g.id for g in registry.available(frozenset({"speech"}))] == no_body
    # the M6 games that are not built yet are known for the keyword map but never offered
    assert {info.id for info in KNOWN_GAMES} - {g.id for g in registry.registered} == {
        "crocodile_human",
    }
    camera_game = StubGame([win()], requires=frozenset({"camera"}))
    registry.register(camera_game)
    assert camera_game not in registry.available(everything)
    assert camera_game in registry.available(everything | {"camera"})
    with_fallback = StubGame([win()], requires=frozenset({"camera"}), fallback_ok=True)
    assert registry.playable(with_fallback, everything)
    assert not registry.playable(StubGame([win()], playable=False), everything)
    assert game_info("quick_draw").phrase == "a duel"


# --- intent ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("heard", "action", "game"),
    [
        ("the cowboy one", "start_game", "quick_draw"),
        ("bang bang", "start_game", "quick_draw"),
        ("the blinking game", "start_game", "staring"),
        ("rock paper scissors", "start_game", "rps_arms"),
        ("charades again", "start_game", "crocodile_robot"),
        ("my turn, I act", "start_game", "crocodile_human"),
        ("again please", "start_game", "quick_draw"),  # the last game
        ("no more games", "stop", None),
        ("I'm done", "stop", None),
        ("which games are there", "list_games", None),
        ("hmm, the weather is nice", "unknown", None),
    ],
)
def test_keyword_fallback_map(heard: str, action: str, game: str | None) -> None:
    intent = keyword_intent(heard, GameRegistry(), last_game="quick_draw")
    assert (intent.action, intent.game) == (action, game)


def test_yes_or_no_for_a_single_game_menu() -> None:
    assert yes_or_no("yes please", "quick_draw") == GameIntent(
        action="start_game", game="quick_draw"
    )
    assert yes_or_no("yes, no problem", "quick_draw").action == "start_game"  # type: ignore[union-attr]
    assert yes_or_no("no", "quick_draw") == GameIntent(action="stop")
    assert yes_or_no("hmm", "quick_draw") is None


def test_again_without_a_last_game_is_unknown() -> None:
    assert keyword_intent("again", GameRegistry(), last_game=None).action == "unknown"


def test_intent_schema_is_validated() -> None:
    assert parse_game_intent(intent_json("start_game", "quick_draw")).game == "quick_draw"
    assert parse_game_intent('```json\n{"action": "stop", "game": null}\n```').action == "stop"
    # an invented game id is no game -> Pipi has to ask
    assert parse_game_intent(intent_json("start_game", "chess")) == GameIntent(
        action="clarify", say="ok"
    )
    assert parse_game_intent(intent_json("start_game")).action == "clarify"
    assert parse_game_intent(intent_json("stop", "quick_draw")).game is None
    for bad in ('{"action": "dance"}', '{"game": "quick_draw"}', "not json", "[1]"):
        with pytest.raises(InvalidModelOutput):
            parse_game_intent(bad)


def test_intent_prompt_lists_only_what_can_be_played() -> None:
    available = [game_info("crocodile_robot"), game_info("quick_draw")]
    unavailable = [game_info("staring")]
    system = build_intent_messages(
        "the duel", available=available, unavailable=unavailable, last_game="crocodile_robot"
    )[0]["content"]
    can, cannot = system.split("cannot play right now")
    assert "quick_draw: the quick-draw duel" in can and "staring" not in can
    assert "staring: the staring contest" in cannot
    assert "They just played: crocodile_robot" in cannot
    assert '"action": "start_game" | "list_games" | "clarify" | "stop" | "unknown"' in system


async def test_understand_uses_the_llm_then_the_keywords(fx: Fixtures) -> None:
    table = await make_game_table(*fx, llm=[intent_json("start_game", "quick_draw")])
    registry = table.s.ctl.registry
    infos = [game.info for game in registry.registered]

    async def ask(text: str) -> tuple[str, str | None, str]:
        got = await understand(table.ctx, text, registry=registry, available=infos, last_game=None)
        return got.intent.action, got.intent.game, got.method

    assert await ask("the one with the shooting") == ("start_game", "quick_draw", "llm")
    table.s.chat.answers = [RuntimeError("down")]
    assert await ask("the cowboy one") == ("start_game", "quick_draw", "keyword")
    assert table.s.data("llm_error")[-1]["purpose"] == "game_intent"
    table.s.chat.answers = ["{ not json"]
    assert await ask("charades") == ("start_game", "crocodile_robot", "keyword")
    # the LLM is unsure, but a keyword is clear
    table.s.chat.answers = [intent_json("unknown")]
    assert await ask("bang!") == ("start_game", "quick_draw", "keyword")
    table.s.chat.answers = [intent_json("clarify")]
    assert await ask("hmm, something fun") == ("clarify", None, "llm")
    table.s.chat.answers = [intent_json("list_games")]
    assert await ask("what is there?") == ("list_games", None, "llm")


@pytest.mark.parametrize(
    ("heard", "choice", "game"),
    [
        ("stop", "stop", None),
        ("that's enough", "stop", None),
        ("another game please", "another_game", None),
        ("let's do the duel instead", "another_game", "quick_draw"),
        ("again!", "continue", None),
        ("yes", "continue", None),
        ("one more guess", "continue", None),  # "guess" is a Crocodile word
    ],
)
def test_between_rounds_keywords(heard: str, choice: str, game: str | None) -> None:
    wish = keyword_between(heard, GameRegistry(), current="crocodile_robot")
    assert wish is not None and (wish.choice, wish.game) == (choice, game)


async def test_between_rounds_asks_the_llm_only_when_keywords_are_not_clear(fx: Fixtures) -> None:
    table = await make_game_table(*fx)
    registry = table.s.ctl.registry
    infos = [game.info for game in registry.registered]

    async def ask(text: str) -> tuple[str, str, str | None]:
        wish = await between_rounds(
            table.ctx, text, registry=registry, available=infos, current="crocodile_robot"
        )
        return wish.choice, wish.method, wish.game

    assert await ask("stop") == ("stop", "keyword", None)
    assert table.s.chat.calls == []  # no LLM call for a clear keyword
    table.s.chat.answers = [intent_json("stop")]
    assert await ask("I would rather read now") == ("stop", "llm", None)
    table.s.chat.answers = [intent_json("start_game", "quick_draw")]
    assert await ask("the fast one") == ("another_game", "llm", "quick_draw")
    table.s.chat.answers = [intent_json("unknown")]
    assert await ask("that was hard") == ("continue", "llm", None)
    table.s.chat.answers = [RuntimeError("down")]
    assert await ask("that was hard") == ("continue", "default", None)


# --- runner ------------------------------------------------------------------------------------


async def test_runner_logs_every_round_and_writes_memory(fx: Fixtures) -> None:
    table = await make_game_table(*fx)
    game = StubGame([win("You won round one!"), RoundResult("robot_won", winner="robot")])
    outcome = await play(table, game)
    assert game.calls == ["start", "explain", "round1", "round2", "finish"]
    assert (outcome.result, outcome.rounds, outcome.fallback) == ("completed", 2, None)
    start = table.s.data("game_start")[0]
    assert start == {
        "game": "stub",
        "placeholder": False,
        "mode": "normal",
        "rounds_planned": 2,
        "missing_requirements": [],
        "fallback": None,
    }
    first, second = table.rounds()
    assert first == {
        "game": "stub",
        "round": 1,
        "mode": "normal",
        "result": "participant_won",
        "winner": "participant",
        "inputs": {"said": "x"},
        "timings": {"reaction_ms": 300, "round_ms": 4000},
        "fallback": None,
    }
    assert (second["round"], second["result"], second["winner"]) == (2, "robot_won", "robot")
    end = table.s.data("game_end")[0]
    assert (end["result"], end["rounds"], end["placeholder"]) == ("completed", 2, False)
    assert end["duration_ms"] == 4000 + 2500 + 4000  # two rounds + the listening window
    events = table.s.ctl.state.memory.game_events
    assert [e.summary for e in events] == ["You won round one!", "We played the stub game."]
    assert table.s.ctl.state.memory.break_highlight == "You won round one!"
    assert table.s.data("memory_update")[-1] == {"fields": ["game_events"]}  # names only


@pytest.mark.parametrize(
    ("said", "result", "line", "rounds"),
    [
        ("stop please", "stopped", "game_stop_ok", 1),
        ("another game", "another_game", "game_switch_ok", 1),
        ("again!", "completed", None, 2),
        (None, "completed", None, 2),  # silence = next round
    ],
)
async def test_between_rounds_again_stop_another_game(
    fx: Fixtures, said: str | None, result: str, line: str | None, rounds: int
) -> None:
    table = await make_game_table(*fx, script=[said])
    game = StubGame([win(), win()])
    outcome = await play(table, game)
    assert (outcome.result, outcome.rounds) == (result, rounds)
    assert table.s.data("game_end")[0]["result"] == result
    if line is not None:
        assert table.s.pipi_lines()[-1] == line
        assert "finish" not in game.calls
    if said is not None:
        choice = table.s.data("game_choice")[0]
        assert choice["context"] == "between_rounds" and choice["heard"] == said
        assert choice["method"] == "keyword" and choice["after_round"] == 1
    else:
        assert table.s.data("game_choice") == []


async def test_another_game_can_already_name_the_game(fx: Fixtures) -> None:
    table = await make_game_table(*fx, script=["let's do the duel"])
    outcome = await play(table, StubGame([win(), win()]))
    assert (outcome.result, outcome.next_game) == ("another_game", "quick_draw")
    assert table.s.data("game_choice")[0]["game"] == "quick_draw"


async def test_a_decided_game_ends_early_and_an_abort_stops_it(fx: Fixtures) -> None:
    table = await make_game_table(*fx)
    best_of_three = StubGame([win(), win(), win()], done_after=2)
    assert (await play(table, best_of_three)).rounds == 2
    assert best_of_three.calls[-1] == "finish"
    broken = StubGame([RoundResult("motion_failed", abort=True), win()])
    outcome = await play(table, broken)
    assert (outcome.result, outcome.rounds) == ("aborted", 1)
    assert "finish" not in broken.calls


async def test_missing_requirement_uses_the_fallback_or_says_sorry(fx: Fixtures) -> None:
    table = await make_game_table(*fx)
    simple = StubGame([win()], requires=frozenset({"camera"}), fallback_ok=True)
    outcome = await play(table, simple)
    assert outcome.result == "completed" and outcome.fallback == "simple"
    start = table.s.data("game_start")[0]
    assert start["missing_requirements"] == ["camera"] and start["fallback"] == "simple"
    assert table.s.data("game_end")[0]["fallback"] == "simple"

    impossible = StubGame([win()], requires=frozenset({"camera"}))
    outcome = await play(table, impossible)
    assert outcome.result == "unavailable" and outcome.rounds == 0
    assert impossible.calls == ["start", "fallback"]  # never explained, never played
    assert table.s.pipi_lines()[-1] == "game_unavailable_now"
    assert table.s.data("game_end")[-1]["result"] == "unavailable"


async def test_cancelled_game_still_logs_the_round_and_the_end(fx: Fixtures) -> None:
    table = await make_game_table(*fx)
    game = StubGame([win(), win()])
    game.block.clear()  # the round never finishes
    task = asyncio.ensure_future(run_game(game, table.ctx, registry=table.s.ctl.registry))
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert table.rounds()[0]["result"] == "interrupted"
    end = table.s.data("game_end")[0]
    assert (end["result"], end["rounds"]) == ("interrupted", 0)


# --- the game context: rules enforced in code ---------------------------------------------------


async def test_silence_blocks_every_kind_of_speech(fx: Fixtures) -> None:
    table = await make_game_table(*fx, script=[None])
    ctx = table.ctx
    with ctx.silence("crocodile_acting"):
        await ctx.say("It is a bird!")
        await ctx.say_line("crocodile_correct", answer="a bird")
        heard = await table.run(ctx.listen(3, eyes="determined"))  # silent: no re-prompt
    assert heard is None
    assert table.robot_did("speak") == []
    assert table.s.tts.texts == [] and table.s.speaker.played == []
    assert [d["speaker"] for d in table.s.data("turn")] == []
    blocked = table.s.data("game_rule_blocked")
    assert [b["blocked"] for b in blocked] == ["say", "crocodile_correct"]
    assert all(b["rule"] == "no_speech" and b["during"] == "crocodile_acting" for b in blocked)
    assert table.robot_did("eyes") == [("eyes", "determined")]
    await ctx.say_line("crocodile_correct", answer="a bird")  # allowed again afterwards
    assert table.robot_did("speak") == [("speak", "Yes! I was a bird! Well guessed!")]


async def test_motions_go_through_the_library(fx: Fixtures) -> None:
    table = await make_game_table(*fx)
    assert await table.ctx.play_motion("act_bird") is True
    assert await table.ctx.play_motion("moonwalk") is False  # not in motions.yaml at all
    assert table.robot_did("motion") == [("motion", "act_bird")]
    # typed session: no microphone, so no bang detector
    assert table.ctx.capabilities == {"speech", "motions", "acting_motions"}
    # back on the pet: it has no acting motions, so act_bird is skipped there (and logged)
    await table.run(table.s.ctl.bodies.migrate_in())
    assert await table.ctx.play_motion("act_bird") is False
    await table.ctx.say_line("crocodile_watch", gesture="act_bird")
    assert ("motion", "act_bird") not in table.s.pet.calls
    skipped = table.s.data("motion_skipped")
    assert [(d["motion"], d["body"]) for d in skipped] == [
        ("moonwalk", "fake_robot"),
        ("act_bird", "desktop_pet"),
        ("act_bird", "desktop_pet"),
    ]


async def test_capabilities_follow_the_microphone_and_the_body(fx: Fixtures) -> None:
    with_mic = await make_game_table(*fx, bang=[])
    assert with_mic.ctx.capabilities == {
        "speech",
        "motions",
        "acting_motions",
        "microphone",
        "bang_detector",
    }
    assert with_mic.ctx.bang_detector is with_mic.s.bang
    no_detector = await make_game_table(*fx, voice=True)
    assert "bang_detector" not in no_detector.ctx.capabilities
    with_mic.s.user.mode = "typed"  # the microphone failed: the session switched to typing
    assert with_mic.ctx.bang_detector is None
    assert "bang_detector" not in with_mic.ctx.capabilities
    # the break runs on the screen (robot missing): the pet has no acting motions
    await with_mic.run(with_mic.s.ctl.bodies.migrate_in())
    assert with_mic.s.ctl.bodies.active_name == "desktop_pet"
    assert with_mic.ctx.capabilities == {"speech", "motions"}
    registry = with_mic.s.ctl.registry
    assert [g.id for g in registry.available(with_mic.ctx.capabilities)] == [
        "quick_draw",
        "staring",
        "rps_arms",
    ]


async def test_woz_signals_reach_a_waiting_game_only() -> None:
    signals = WozSignals()
    assert signals.publish("duel_hit") is False  # nobody waits: nothing happens
    waiter = asyncio.ensure_future(signals.wait({"duel_hit", "duel_win"}))
    await asyncio.sleep(0)
    assert signals.publish("nod") is False and not waiter.done()
    assert signals.publish("duel_win") is True
    assert await waiter == "duel_win"
    cancelled = asyncio.ensure_future(signals.wait({"duel_hit"}))
    await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.gather(cancelled, return_exceptions=True)
    assert signals.publish("duel_hit") is False  # the cancelled waiter is gone
