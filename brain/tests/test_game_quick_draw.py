"""Quick-draw duel: the bang detector, the race, false starts and every fallback.

Played on the real session game context with a fake robot body, a ``FakeBangDetector`` and
virtual time. ``ScriptedRng`` makes the randomness readable: ``uniforms`` are, per round,
[wait before green in s, the robot's reaction in ms (only when it plays to win)];
``randoms`` < 0.3 = the robot plays to win this round, else it lets the participant win.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.fakes import FakeBody, FakeMicrophone, make_frames
from pipi_brain.games.setup import GameSetup, build_registry, load_game_setup
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.bang import BangDetectorError, MicBangDetector
from pipi_brain.speech.base import Utterance

from .session_harness import GameTable, ScriptedRng, make_game_table

Fixtures = tuple[LoadedConfig, DialogueContent, Path]
GAME = "quick_draw"
WAIT = 3.5  # ScriptedRng default: the middle of delay_range_s [2, 5]


@pytest.fixture
def fx(dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path) -> Fixtures:
    return dev_config, dialogue_content, tmp_path


async def duel_table(fx: Fixtures, *, games: dict[str, Any] | None = None, **kw: Any) -> GameTable:
    """A table for the duel. ``games``: top-level games.yaml values to replace."""
    loaded, content, tmp_path = fx
    table = await make_game_table(loaded, content, tmp_path, **kw)
    base = load_game_setup(loaded.app.games)
    config = base.config.model_copy(update={"between_rounds_s": 0, **(games or {})})
    setup = GameSetup(config, base.motions, build_registry(config))
    table.s.ctl.ctx.games = setup
    table.ctx.config = setup.config
    table.s.ctl.registry = setup.registry
    return table


def said(text: str) -> Utterance:
    """A spoken utterance; the fake STT answers come from ``table.s.stt.answers``."""
    return Utterance(np.zeros(1600, dtype=np.float32), 16000, 0.0, 0.1, False)


def results(table: GameTable) -> list[tuple[str, str]]:
    return [(r["result"], r["inputs"]["reason"]) for r in table.rounds()]


# --- the detector ------------------------------------------------------------------------------


async def test_mic_detector_finds_the_first_loud_frame() -> None:
    # 10 quiet frames, then loud ones (sine 0.5 = about -9 dBFS); 32 ms per frame from t=100
    frames = make_frames([(0.01, 10), (0.5, 3)])
    detector = MicBangDetector(
        FakeMicrophone(frames), threshold_db=-20, frame_timeout_s=1, monotonic=lambda: 100.0
    )
    bang = await detector.wait_for_bang()
    assert bang.at == pytest.approx(100.0 + 10 * 0.032)
    assert -10 < bang.level_db < -8
    assert detector.now() == 100.0


async def test_mic_detector_ignores_audio_from_before_it_was_armed() -> None:
    frames = make_frames([(0.5, 5), (0.0, 5), (0.5, 1)])  # loud (Pipi's own voice), quiet, bang
    armed_at = 100.0 + 5 * 0.032
    detector = MicBangDetector(
        FakeMicrophone(frames), threshold_db=-20, frame_timeout_s=1, monotonic=lambda: armed_at
    )
    bang = await detector.wait_for_bang()
    assert bang.at == pytest.approx(100.0 + 10 * 0.032)


async def test_mic_detector_is_not_blocked_by_the_audio_gate() -> None:
    """The half-duplex gate would reject these frames (Pipi "speaking" / the tail after it)."""
    frames = make_frames([(0.0, 2), (0.5, 1)])
    gate = AudioGate(tail_ms=300, clock=lambda: 100.0)
    with gate.speaking():
        assert not gate.accepts(frames[2].captured_at)  # normal listening would drop it
        detector = MicBangDetector(
            FakeMicrophone(frames), threshold_db=-20, frame_timeout_s=1, monotonic=lambda: 100.0
        )
        assert (await detector.wait_for_bang()).at == pytest.approx(100.064)
    assert not gate.accepts(100.1)  # the tail is still closed for listening


async def test_mic_detector_reports_a_dead_microphone() -> None:
    detector = MicBangDetector(
        FakeMicrophone(make_frames([(0.0, 3)])), threshold_db=-20, frame_timeout_s=1
    )
    with pytest.raises(BangDetectorError, match="no more frames"):
        await detector.wait_for_bang()


# --- the race (detector mode) ---


async def test_participant_shoots_first_and_wins_two_nil(fx: Fixtures) -> None:
    # bang 0.38 s and 0.42 s after green; the robot plays to win both rounds (600 / 700 ms)
    table = await duel_table(
        fx,
        bang=[WAIT + 0.38, WAIT + 0.42],
        rng=ScriptedRng(uniforms=[WAIT, 600, WAIT, 700], randoms=[0.1, 0.1]),
    )
    outcome = await table.play(GAME)
    assert (outcome.result, outcome.rounds, outcome.fallback) == ("completed", 2, None)
    assert results(table) == [("participant_won", "faster")] * 2
    first = table.rounds()[0]
    assert first["mode"] == "detector" and first["fallback"] is None
    assert first["timings"]["delay_ms"] == 3500
    assert first["timings"]["participant_reaction_ms"] == 380
    assert first["timings"]["robot_reaction_ms"] == 600
    assert first["inputs"]["robot_played_to_win"] is True and first["inputs"]["level_db"] == -6.0
    assert first["inputs"]["score"] == {"participant": 1, "robot": 0}
    assert table.rounds()[1]["timings"]["participant_reaction_ms"] == 420
    assert table.s.pipi_lines() == [
        "quick_draw_rules",
        "quick_draw_round",
        "quick_draw_you_win",
        "quick_draw_round",
        "quick_draw_you_win",
        "quick_draw_final_you",
    ]
    assert table.s.pipi_said()[-1] == "You win the duel, 2 to 0! Fastest hands in the west."
    assert table.s.ctl.state.memory.game_events[-1].summary == (
        "You beat me in the quick-draw duel, 2 to 0!"
    )
    assert table.s.bang is not None and table.s.bang.armed == 2


async def test_one_round_choreography(fx: Fixtures) -> None:
    table = await duel_table(fx, bang=[WAIT + 0.5, WAIT + 0.5])
    await table.play(GAME)
    calls = table.robot_did("motion", "eyes", "speak")
    ready = calls.index(("motion", "duel_ready"))
    assert calls[ready - 1] == ("speak", "Round 1. Ready?")
    # ready pose -> countdown eyes -> (silence) -> green -> the robot is hit -> it speaks again
    assert calls[ready : ready + 5] == [
        ("motion", "duel_ready"),
        ("eyes", "countdown"),
        ("eyes", "signal_go"),
        ("motion", "duel_hit"),  # also ends the held ready pose
        ("speak", "Argh, you got me!"),
    ]


class SlowAckBody(FakeBody):
    """A robot body whose green eyes take 40 ms (virtual) to arrive and be acked."""

    clock: Any = None

    async def set_eyes(self, state: Any) -> Any:
        if state == "signal_go":
            await self.clock.sleep(0.04)
        return await super().set_eyes(state)


async def test_reaction_time_counts_from_the_acked_green(fx: Fixtures) -> None:
    robot = SlowAckBody(name="fake_robot")
    table = await duel_table(
        fx,
        bodies={"desktop_pet": FakeBody(name="desktop_pet"), "fake_robot": robot},
        bang=[WAIT + 0.54, WAIT + 0.54],
        rng=ScriptedRng(uniforms=[WAIT, 800, WAIT, 800], randoms=[0.1, 0.1]),
    )
    robot.clock = table.s.clock
    await table.play(GAME)
    first = table.rounds()[0]
    # green was sent at 3.5 s and acked at 3.54 s; the bang came at 4.04 s
    assert first["timings"]["participant_reaction_ms"] == 500
    assert first["inputs"]["green_acked"] is True
    # the robot's own 800 ms also start at the ack: it would have drawn at 4.34 s
    assert first["result"] == "participant_won"


async def test_the_go_sound_is_not_a_bang(fx: Fixtures) -> None:
    """The fake robot beeps when its eyes turn green: spikes right after green are ignored."""
    table = await duel_table(
        fx,
        # round 1: the beep 60 ms after green, again 100 ms later (still inside the 300 ms
        # window), then the real shout 300 ms after that = 460 ms after green.
        # round 2: only the beep; nobody shoots -> the robot (it lets you win) waits, then draws
        bang=[WAIT + 0.06, 0.1, 0.3, WAIT + 0.06, None],
    )
    await table.play(GAME)
    first, second = table.rounds()[:2]
    assert first["result"] == "participant_won"
    assert first["timings"]["participant_reaction_ms"] == 460
    assert first["inputs"]["ignored_after_green"] == 2
    assert first["inputs"]["false_start"] is False
    assert (second["result"], second["inputs"]["reason"]) == ("robot_won", "too_slow")
    assert second["inputs"]["ignored_after_green"] == 1
    assert second["timings"]["participant_reaction_ms"] is None


async def test_a_spike_while_green_is_on_its_way_is_the_go_sound_or_too_early(
    fx: Fixtures,
) -> None:
    robot = SlowAckBody(name="fake_robot")
    table = await duel_table(
        fx,
        bodies={"desktop_pet": FakeBody(name="desktop_pet"), "fake_robot": robot},
        # round 1: a spike 20 ms after the eyes were sent (before the ack): the go sound ->
        # ignored; the real bang 600 ms later. Round 2: a spike 10 ms BEFORE green: false start
        bang=[WAIT + 0.02, 0.6, WAIT - 0.01, WAIT + 0.5, WAIT + 0.5],
    )
    robot.clock = table.s.clock
    await table.play(GAME)
    first, second = table.rounds()[:2]
    assert first["result"] == "participant_won" and first["inputs"]["ignored_after_green"] == 1
    # armed again when the ack arrived (3.54 s); the bang 600 ms later
    assert first["timings"]["participant_reaction_ms"] == 600
    assert (second["result"], second["inputs"]["reason"]) == ("robot_won", "false_start")
    assert second["timings"]["false_start_ms"] == 3490


async def test_typed_enter_inside_the_blank_window_is_ignored_too(fx: Fixtures) -> None:
    table = await duel_table(fx, script=[("", WAIT + 0.1), ("", 0.4), ("", WAIT + 0.4)])
    await table.play(GAME)
    first = table.rounds()[0]
    assert first["inputs"]["ignored_after_green"] == 1
    assert first["timings"]["participant_reaction_ms"] == 500


async def test_robot_wins_when_it_is_faster_or_you_are_too_slow(fx: Fixtures) -> None:
    table = await duel_table(
        fx,
        bang=[WAIT + 0.8, None],  # round 1: slower than the robot's 500 ms; round 2: no shot
        rng=ScriptedRng(uniforms=[WAIT, 500, WAIT], randoms=[0.1, 0.9]),
    )
    outcome = await table.play(GAME)
    assert outcome.rounds == 2
    assert results(table) == [("robot_won", "faster"), ("robot_won", "too_slow")]
    first, second = table.rounds()
    assert first["timings"]["robot_reaction_ms"] == 500
    assert first["timings"]["participant_reaction_ms"] is None
    assert second["inputs"]["robot_played_to_win"] is False
    assert second["timings"]["robot_reaction_ms"] == 4000  # give_up_s: it waited for you
    motions = [arg for _, arg in table.robot_did("motion")]
    assert motions.count("duel_draw") == 2 and motions.count("duel_win") == 2
    assert "duel_hit" not in motions
    lines = table.s.pipi_lines()
    assert "quick_draw_robot_wins" in lines and "quick_draw_too_slow" in lines
    assert table.s.pipi_said()[-1] == "I win the duel, 2 to 0! Good duel, partner."
    assert table.s.ctl.state.memory.game_events[-1].summary == "I won our quick-draw duel, 2 to 0."


async def test_good_sport_lets_the_participant_win_most_rounds(fx: Fixtures) -> None:
    # a slow participant (1.5 s): wins anyway when the robot is a good sport (roll >= 0.3)
    table = await duel_table(
        fx, bang=[WAIT + 1.5, WAIT + 1.5], rng=ScriptedRng(randoms=[0.5, 0.31])
    )
    await table.play(GAME)
    assert results(table) == [("participant_won", "faster")] * 2
    assert table.rounds()[0]["timings"]["participant_reaction_ms"] == 1500
    # the same participant against a robot that always plays to win
    serious = await duel_table(
        (fx[0], fx[1], fx[2] / "serious"),
        games={"good_sport": False},
        bang=[WAIT + 1.5, WAIT + 1.5],
        rng=ScriptedRng(uniforms=[WAIT, 450, WAIT, 900], randoms=[0.99, 0.99]),
    )
    await serious.play(GAME)
    assert results(serious) == [("robot_won", "faster")] * 2
    assert serious.s.rng.randoms == [0.99, 0.99]  # no dice rolled: it always tries


async def test_false_start_loses_the_round(fx: Fixtures) -> None:
    table = await duel_table(fx, bang=[1.2, WAIT + 0.3, WAIT + 0.3])
    outcome = await table.play(GAME)
    assert outcome.rounds == 3  # 0-1, 1-1, 2-1: best of 3 goes the full distance
    assert results(table)[0] == ("robot_won", "false_start")
    first = table.rounds()[0]
    assert first["inputs"]["false_start"] is True
    assert first["timings"]["false_start_ms"] == 1200
    assert first["timings"]["participant_reaction_ms"] is None
    assert table.s.pipi_lines()[2] == "quick_draw_false_start"
    calls = table.robot_did("eyes")
    assert calls[:2] == [("eyes", "countdown"), ("eyes", "countdown")]  # never green in round 1
    assert table.s.pipi_said()[-1].startswith("You win the duel, 2 to 1!")
    assert table.rounds()[-1]["inputs"]["score"] == {"participant": 2, "robot": 1}


# --- fallback (b): the detector is unreliable -> slow-motion duel ---


async def test_room_noise_switches_to_the_slow_motion_duel(fx: Fixtures) -> None:
    """A "bang" 100 ms after arming is noise: slow-motion duel, the round is played again."""
    table = await duel_table(
        fx,
        bang=[0.1],
        script=[(said("bang"), WAIT + 1.0), (said("bang"), WAIT + 1.0)],
    )
    table.s.stt.answers = ["Bang!", "bang bang"]
    outcome = await table.play(GAME)
    assert (outcome.result, outcome.rounds, outcome.fallback) == ("completed", 2, "slow_motion")
    fallback = table.s.data("game_fallback")[0]
    assert (fallback["from"], fallback["to"]) == ("detector", "slow_motion")
    assert "100 ms after arming" in fallback["reason"]
    assert table.s.pipi_lines()[:4] == [
        "quick_draw_rules",
        "quick_draw_round",
        "quick_draw_slow_motion",  # "This is a slow-motion duel!"
        "quick_draw_round",  # the same round again
    ]
    first = table.rounds()[0]
    assert first["round"] == 1 and first["inputs"]["replays"] == 1
    assert (first["mode"], first["fallback"]) == ("slow_motion", "slow_motion")
    assert first["result"] == "participant_won" and first["inputs"]["heard"] == "Bang!"
    assert first["timings"]["participant_reaction_ms"] == 1000
    assert table.s.bang is not None and table.s.bang.armed == 1  # never used again
    assert table.s.data("game_end")[0]["fallback"] == "slow_motion"


async def test_detector_failure_switches_to_slow_motion(fx: Fixtures) -> None:
    table = await duel_table(fx, bang=[BangDetectorError("no audio for 2 s")])
    await table.play(GAME)
    assert "bang detector failed" in table.s.data("game_fallback")[0]["reason"]
    assert table.rounds()[0]["mode"] == "slow_motion"
    # nobody says bang: in slow motion the robot waits 8 s (it lets you win), then draws
    assert results(table) == [("robot_won", "too_slow")] * 2
    assert table.rounds()[0]["timings"]["robot_reaction_ms"] == 8000


async def test_slow_motion_from_the_start_hears_bang_through_stt(fx: Fixtures) -> None:
    """A microphone but no detector: slow-motion rules; only "bang" counts as a shot."""
    table = await duel_table(
        fx,
        voice=True,
        script=[
            (said("wait"), WAIT + 0.5),
            (said("bang"), 1.0),
            (said("?"), WAIT + 1.0),
            (said("early"), 1.0),
        ],
        rng=ScriptedRng(uniforms=[WAIT, WAIT, WAIT], randoms=[0.9, 0.9, 0.9]),
    )
    table.s.stt.answers = ["wait, what do I do?", "bang", RuntimeError("stt down"), "pew pew"]
    outcome = await table.play(GAME)
    assert outcome.fallback == "slow_motion"
    assert table.s.data("game_start")[0]["missing_requirements"] == ["bang_detector"]
    assert table.s.pipi_lines()[0] == "quick_draw_rules_slow"
    first, second = table.rounds()  # two wins end the duel: there is no third round
    # round 1: "wait, what do I do?" is not a shot; "bang" 1.5 s after green is
    assert first["result"] == "participant_won" and first["inputs"]["heard"] == "bang"
    assert first["timings"]["participant_reaction_ms"] == 1500
    # round 2: a shout the STT could not transcribe still counts (lenient)
    assert second["result"] == "participant_won" and second["inputs"]["understood"] is False
    assert second["timings"]["participant_reaction_ms"] == 1000


async def test_slow_motion_duel_ends_after_two_wins(fx: Fixtures) -> None:
    table = await duel_table(
        fx, voice=True, script=[(said("bang"), WAIT + 1), (said("bang"), WAIT + 1)]
    )
    table.s.stt.answers = ["bang", "bang"]
    outcome = await table.play(GAME)
    assert outcome.rounds == 2 and results(table) == [("participant_won", "faster")] * 2


# --- fallback (a): a typed session ---


async def test_typed_mode_enter_is_the_bang(fx: Fixtures) -> None:
    table = await duel_table(fx, script=[("", WAIT + 0.4), ("x", 1.0), ("bang", WAIT + 0.5)])
    outcome = await table.play(GAME)
    assert outcome.fallback == "typed"
    assert table.s.pipi_lines()[0] == "quick_draw_rules_typed"
    fallback = table.s.data("game_fallback")[0]
    assert (fallback["to"], fallback["reason"]) == ("typed", "no bang detector")
    first, second, third = table.rounds()
    assert first["result"] == "participant_won" and first["mode"] == "typed"
    assert first["timings"]["participant_reaction_ms"] == 400
    assert second["inputs"]["false_start"] is True and second["timings"]["false_start_ms"] == 1000
    assert third["result"] == "participant_won" and third["fallback"] == "typed"
    # a bare Enter is a shot, not something the participant "said"
    assert [d["text"] for d in table.s.data("turn") if d["speaker"] == "user"] == ["x", "bang"]


async def test_microphone_failure_between_rounds_switches_to_typing(fx: Fixtures) -> None:
    table = await duel_table(fx, bang=[WAIT + 0.5], script=[("", WAIT + 0.5)])

    async def microphone_dies() -> None:
        await table.s.clock.sleep(1.0)  # during round 1 (which still finishes normally)
        table.s.user.mode = "typed"  # what TerminalSessionInput does when the mic fails

    await table.play(GAME, microphone_dies())
    first, second = table.rounds()
    assert (first["mode"], first["result"]) == ("detector", "participant_won")
    assert (second["mode"], second["inputs"]["shot_by"]) == ("typed", "typed")
    assert second["inputs"]["replays"] == 1 and second["result"] == "participant_won"
    fallback = table.s.data("game_fallback")[0]
    assert fallback["to"] == "typed" and "not available any more" in fallback["reason"]
    assert "quick_draw_rules_typed" in table.s.pipi_lines()  # Pipi explains the new way


# --- fallback (c): the experimenter scores the round ---


async def test_woz_scores_a_round_with_play_motion(fx: Fixtures) -> None:
    table = await duel_table(fx, bang=[None, None])

    async def experimenter() -> None:
        await table.s.clock.sleep(1.0)  # during the countdown of round 1
        assert (await table.s.woz("play_motion", "technical_failure", name="duel_hit")).ok
        await table.s.clock.sleep(WAIT + 2.0)  # round 2, after green
        assert (await table.s.woz("play_motion", "technical_failure", name="duel_hit")).ok

    outcome = await table.play(GAME, experimenter())
    assert outcome.rounds == 2
    assert results(table) == [("participant_won", "woz")] * 2
    assert all(r["inputs"]["scored_by"] == "woz" for r in table.rounds())
    assert table.rounds()[0]["inputs"]["woz_motion"] == "duel_hit"
    motions = [arg for _, arg in table.robot_did("motion")]
    assert motions.count("duel_hit") == 2  # played by the WoZ command, not again by the game
    assert len(table.s.data("woz_action")) == 2


async def test_woz_can_give_the_round_to_the_robot(fx: Fixtures) -> None:
    table = await duel_table(fx, bang=[None, None, None])

    async def experimenter() -> None:
        for _ in range(2):
            await table.s.clock.sleep(1.0)
            await table.s.woz("play_motion", "demo", name="duel_win")
            await table.s.clock.sleep(3.0)

    await table.play(GAME, experimenter())
    assert results(table) == [("robot_won", "woz")] * 2
    assert "duel_draw" not in [arg for _, arg in table.robot_did("motion")]


# --- pause ---


async def test_a_pause_during_the_countdown_replays_the_round(fx: Fixtures) -> None:
    table = await duel_table(fx, bang=[None, WAIT + 0.3, WAIT + 0.3])
    pause = table.s.ctl.pause

    async def experimenter() -> None:
        await table.s.clock.sleep(1.0)
        pause.pause()
        await table.s.clock.sleep(30.0)
        pause.resume()

    await table.play(GAME, experimenter())
    first = table.rounds()[0]
    assert first["inputs"]["replays"] == 1 and first["result"] == "participant_won"
    assert table.s.pipi_lines()[1:3] == ["quick_draw_round", "quick_draw_round"]
    assert table.s.bang is not None and table.s.bang.armed == 3  # disarmed while paused
    motions = [arg for _, arg in table.robot_did("motion")]
    assert motions[:3] == ["excited", "duel_ready", "idle"]  # the held pose is let go
    assert table.s.ctl.ctx.woz_signals._waiters == []  # nothing left waiting
