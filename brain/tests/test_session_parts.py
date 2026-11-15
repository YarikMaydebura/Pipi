"""Small session building blocks: timers, safe points, the virtual clock, game registry,
flow table, persona matching and the session config section."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pipi_brain.config import ConfigError, load_config
from pipi_brain.fakes import FakeClock
from pipi_brain.games.registry import GameRegistry
from pipi_brain.memory import Memory
from pipi_brain.phases.flow import BREAK_PHASES, PET_PHASES, PHASES, side_of, successor
from pipi_brain.phases.persona_pick import match_persona
from pipi_brain.phases.timers import Countdown, PauseState, SafePoints

from .conftest import CONFIG_DIR, REPO_ROOT


async def test_countdown_respects_pause_and_extend() -> None:
    clock = FakeClock()
    pause = PauseState(clock)
    timer = Countdown("focus", 30, pause, clock)
    await clock.advance(10)
    assert timer.remaining_s == pytest.approx(20)
    pause.pause()
    await clock.advance(100)
    assert timer.remaining_s == pytest.approx(20) and pause.paused
    pause.resume()
    timer.extend(10)
    done = asyncio.ensure_future(timer.wait_expired())
    await clock.advance(29)
    assert not done.done()
    await clock.advance(1)
    assert done.done() and timer.expired
    assert timer.info().total_s == 40


async def test_pause_and_resume_report_double_calls() -> None:
    pause = PauseState(FakeClock())
    assert pause.pause() and not pause.pause()
    assert pause.resume() and not pause.resume()


async def test_safe_point_interrupt_waits_for_the_utterance() -> None:
    safe = SafePoints()
    order: list[str] = []
    release = asyncio.Event()

    async def phase() -> None:
        async with safe.critical():
            order.append("speaking")
            await release.wait()
            order.append("finished sentence")
        await asyncio.sleep(10)  # cancelled here, right after the sentence

    task = asyncio.ensure_future(phase())
    await asyncio.sleep(0)
    interrupt = asyncio.ensure_future(safe.interrupt(task))
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    await interrupt
    assert task.cancelled()
    assert order == ["speaking", "finished sentence"]


async def test_new_utterances_wait_while_an_interrupt_is_pending() -> None:
    safe = SafePoints()
    started: list[str] = []

    async def first() -> None:
        async with safe.critical():
            await asyncio.sleep(0)

    async def second() -> None:
        async with safe.critical():
            started.append("second")

    target = asyncio.ensure_future(first())
    await asyncio.sleep(0)
    interrupt = asyncio.ensure_future(safe.interrupt(target))
    other = asyncio.ensure_future(second())
    await interrupt
    await asyncio.sleep(0)
    await other  # released after the interrupt
    assert started == ["second"]


async def test_fake_clock_advance_wakes_sleepers_in_order() -> None:
    clock = FakeClock(start=0)
    woke: list[float] = []

    async def sleeper(seconds: float) -> None:
        await clock.sleep(seconds)
        woke.append(clock.now())

    tasks = [asyncio.ensure_future(sleeper(s)) for s in (3, 1, 2)]
    await clock.advance(2.5)
    assert woke == [1, 2]
    await clock.advance(1)
    assert woke == [1, 2, 3]
    await asyncio.gather(*tasks)


def test_flow_table_covers_every_phase() -> None:
    for phase in PHASES:
        if phase != "END":
            assert successor(phase, game_loop=False) is not None
    assert successor("GAME_CHOSEN", game_loop=True) == "GAME_MENU"
    assert successor("END", game_loop=False) is None
    assert side_of("FOCUS") == "pet" and side_of("CHAT") == "robot"
    assert side_of("MIGRATE_OUT") is None
    assert not PET_PHASES & BREAK_PHASES


@pytest.mark.parametrize(
    ("heard", "game"),
    [
        ("the cowboy one", "quick_draw"),
        ("let's do a duel", "quick_draw"),
        ("the blinking game", "staring"),
        ("rock paper scissors!", "rps_arms"),
        ("charades again", "crocodile_robot"),
        ("my turn, I act", "crocodile_human"),
        ("I don't know", None),
    ],
)
def test_game_keyword_fallback(heard: str, game: str | None) -> None:
    assert GameRegistry().match_keyword(heard) == game


def test_stop_words_and_registry_hook() -> None:
    registry = GameRegistry()
    assert registry.wants_stop("no more games please")
    assert not registry.wants_stop("the duel")
    assert registry.implementation("quick_draw") is None
    assert set(registry.known) == {
        "crocodile_robot",
        "quick_draw",
        "staring",
        "rps_arms",
        "crocodile_human",
    }


def test_persona_matching(dialogue_content: object) -> None:
    personas = dict(dialogue_content.personas)  # type: ignore[attr-defined]
    assert match_persona("Calm please", personas) == "calm"
    assert match_persona("the funny one", personas) == "witty"
    assert match_persona("first", personas) == "cheerful"
    assert match_persona("hmm", personas) is None


def test_memory_helpers_return_new_objects() -> None:
    memory = Memory(participant_id="P01", persona="cheerful")
    changed = memory.with_persona("calm").add_word_help("lucid", "FOCUS", 1)
    changed = changed.add_game_event("quick_draw", "won the duel 2-1")
    assert memory.persona == "cheerful" and memory.word_help == ()
    assert changed.persona == "calm" and changed.word_help[0].term == "lucid"
    assert changed.break_highlight == "won the duel 2-1"


@pytest.mark.parametrize("mode", ["dev", "study", "demo"])
def test_session_config_loads_in_every_mode(mode: str) -> None:
    app = load_config(CONFIG_DIR / f"{mode}.yaml").app
    assert app.session.chat_max_exchanges == 3
    assert app.session.default_game in GameRegistry().known
    assert app.tts_cache.dir == REPO_ROOT / "cache" / "tts"


def test_session_overrides_per_mode() -> None:
    dev = load_config(CONFIG_DIR / "dev.yaml").app.session
    study = load_config(CONFIG_DIR / "study.yaml").app.session
    demo = load_config(CONFIG_DIR / "demo.yaml").app.session
    assert dev.game_placeholder_s < study.game_placeholder_s
    assert dev.return_end_s == 15 and study.return_end_s is None
    assert demo.game_loop and not study.game_loop and not dev.game_loop


def test_invalid_session_value_is_rejected(tmp_config_dir: Path) -> None:
    cfg = tmp_config_dir / "bad.yaml"
    cfg.write_text("extends: base.yaml\nmode: dev\nsession:\n  flight_s: 30\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="flight_s"):
        load_config(cfg)
