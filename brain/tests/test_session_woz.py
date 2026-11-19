"""WoZ control of a running session: validation of every command, flow commands, pause,
emergency stop, state pushes. The controller is the WozBackend the WoZ server talks to."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.fakes import FakeBody
from pipi_brain.phases.terminal_commands import HELP, parse_terminal_command
from pipi_brain.phases.woz_commands import COMMAND_ARGS, validate_command
from pipi_brain.protocol import Alert, StateUpdate, Turn, WozCommand
from pipi_brain.woz_api import WozBackend

from .session_harness import Session, make_session


def waiting(loaded: LoadedConfig, content: DialogueContent, tmp_path: Path, **kw: Any) -> Session:
    """A session that waits in SETUP for start_session (as with a WoZ panel)."""
    return make_session(loaded, content, tmp_path, auto_start=False, **kw)


async def settle(s: Session, seconds: float = 0.0) -> None:
    """Let the session run for ``seconds`` of virtual time (0 = just let tasks catch up)."""
    target = s.clock.now() + seconds
    for _ in range(500_000):
        if s.clock.now() >= target:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("virtual time did not advance")
    for _ in range(300):
        await asyncio.sleep(0)


def cmd(command: str, reason: str = "timing", note: str | None = None, **args: Any) -> WozCommand:
    return WozCommand(command=command, args=args, reason=reason, note=note)  # type: ignore[arg-type]


# --- argument validation (pure) ----------------------------------------------------------------

BAD_ARGS: list[tuple[str, dict[str, Any]]] = [
    ("start_session", {"override": "yes"}),
    ("start_session", {"participant_id": ""}),
    ("next_phase", {"phase": "CHAT"}),
    ("goto_phase", {}),
    ("goto_phase", {"phase": "LUNCH"}),
    ("extend_focus", {"seconds": "60"}),
    ("extend_focus", {"seconds": 0}),
    ("extend_focus", {"seconds": 10_000}),
    ("extend_focus", {"seconds": True}),
    ("trigger_migration_out", {"now": True}),
    ("trigger_migration_in", {"x": 1}),
    ("say", {}),
    ("say", {"line_id": "Not A Name!"}),
    ("say_text", {"text": "   "}),
    ("say_text", {"text": "x" * 301}),
    ("say_text", {"text": 5}),
    ("start_game", {}),
    ("start_game", {"game": "Quick Draw"}),
    ("end_game", {"game": "quick_draw"}),
    ("switch_robot_body", {"body": "alpha"}),
    ("switch_robot_body", {}),
    ("set_eyes", {"state": "angry"}),
    ("set_eyes", {"state": "happy", "body": "My Body"}),
    ("play_motion", {"name": ""}),
    ("play_motion", {"name": "wave", "speed": 2}),
    ("pause", {"seconds": 5}),
    ("resume", {"x": 1}),
    ("emergency_stop", {"really": True}),
    ("end_session", {"now": True}),
]


def test_every_command_has_argument_rules() -> None:
    from typing import get_args

    from pipi_brain.protocol import WozCommandName

    assert set(COMMAND_ARGS) == set(get_args(WozCommandName))


@pytest.mark.parametrize(("command", "args"), BAD_ARGS)
def test_bad_arguments_are_rejected(command: str, args: dict[str, Any]) -> None:
    assert validate_command(cmd(command, **args)) is not None


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("start_session", {"participant_id": "P01", "override": True}),
        ("goto_phase", {"phase": "CHAT"}),
        ("extend_focus", {"seconds": 60}),
        ("extend_focus", {"seconds": 30.5}),
        ("say", {"line_id": "stt_retry"}),
        ("say_text", {"text": "Hello!"}),
        ("start_game", {"game": "quick_draw"}),
        ("switch_robot_body", {"body": "fake"}),
        ("set_eyes", {"state": "happy", "body": "fake_robot"}),
        ("play_motion", {"name": "wave"}),
        ("emergency_stop", {}),
    ],
)
def test_good_arguments_pass(command: str, args: dict[str, Any]) -> None:
    assert validate_command(cmd(command, **args)) is None


def test_reason_other_needs_a_note() -> None:
    assert "note" in (validate_command(cmd("pause", reason="other")) or "")
    assert validate_command(cmd("pause", reason="other", note="observer asked")) is None


async def test_rejected_commands_are_answered_and_logged(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    for command, args in BAD_ARGS:
        outcome = await s.ctl.handle_woz(cmd(command, **args))
        assert not outcome.ok and outcome.error
    actions = s.data("woz_action")
    assert len(actions) == len(BAD_ARGS)
    assert all(a["ok"] is False and a["reason"] == "timing" for a in actions)


def test_controller_is_a_woz_backend(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    backend: WozBackend = waiting(dev_config, dialogue_content, tmp_path).ctl
    snap = backend.snapshot()
    assert snap.phase == "SETUP" and snap.mode == "dev" and snap.participant_id == "P01"
    assert set(snap.health) == {"desktop_pet", "fake_robot"}


# --- flow commands -----------------------------------------------------------------------------


async def test_start_session_and_wrong_participant(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    await settle(s, 5)
    assert s.ctl.state.phase == "SETUP"  # waits for the experimenter
    wrong = await s.woz("start_session", participant_id="P99")
    assert not wrong.ok and "P01" in (wrong.error or "")
    assert (await s.woz("start_session", participant_id="P01")).ok
    await s.until_phase("PERSONA_PICK")
    assert not (await s.woz("start_session")).ok  # already started
    assert (await s.woz("end_session")).ok
    await task
    first = s.data("phase_change")[0]
    assert first == {
        "from": "SETUP",
        "to": "PERSONA_PICK",
        "trigger": "woz",
        "command": "start_session",
        "reason": "timing",
    }
    assert s.phases()[-1] == "END"
    assert not (await s.woz("next_phase")).ok  # ended


async def test_study_mode_needs_green_health_or_override(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path, mode="study", robot_connected=False)
    task = s.start()
    refused = await s.woz("start_session")
    assert not refused.ok and "fake_robot not connected" in (refused.error or "")
    assert (await s.woz("start_session", override=True)).ok
    await s.until_phase("PERSONA_PICK")
    await s.woz("end_session")
    await task
    checks = [c for c in s.data("health_check") if "override" in c]
    assert checks == [{**checks[0], "override": True}]
    assert checks[0]["fake_robot"] == "not connected"


async def test_next_phase_and_goto_across_bodies_runs_the_migration(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    await s.woz("next_phase")  # in SETUP = start_session
    await s.until_phase("PERSONA_PICK")
    await s.woz("next_phase")
    await s.until_phase("GREETING")
    await s.woz("goto_phase", phase="CHAT")
    await s.until_phase("CHAT")
    assert s.ctl.bodies.active_name == "fake_robot"
    await s.woz("goto_phase", phase="FOCUS")
    await s.until_phase("FOCUS")
    assert s.ctl.bodies.active_name == "desktop_pet"
    assert not (await s.woz("goto_phase", phase="SETUP")).ok
    await s.woz("end_session")
    await task
    assert s.phases() == [
        "PERSONA_PICK",
        "GREETING",
        "MIGRATE_OUT",
        "CHAT",
        "MIGRATE_IN",
        "FOCUS",
        "END",
    ]
    via = [c for c in s.data("phase_change") if c.get("via")]
    assert via[0]["requested"] == "CHAT" and via[0]["via"] == "MIGRATE_OUT"
    assert ("calm", False) in s.pet.calls  # FOCUS cut short still turns calm off


async def test_extend_focus_adds_time(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    assert not (await s.woz("extend_focus", seconds=60)).ok  # not in FOCUS
    await s.woz("goto_phase", phase="FOCUS")
    await s.until_phase("FOCUS")
    assert (await s.woz("extend_focus", seconds=60)).ok  # may arrive before the timer starts
    await settle(s)
    assert s.ctl.snapshot().timer.total_s == 90  # type: ignore[union-attr]
    assert (await s.woz("extend_focus", seconds=10)).ok  # running timer
    assert s.ctl.snapshot().timer.total_s == 100  # type: ignore[union-attr]
    await s.until_phase("MIGRATE_OUT")
    await s.woz("end_session")
    await task
    assert s.ctl.state.phase_durations_s["FOCUS"] == pytest.approx(100)


async def test_migration_commands(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    assert not (await s.woz("trigger_migration_out")).ok  # SETUP
    await s.woz("start_session")
    await s.until_phase("PERSONA_PICK")
    assert not (await s.woz("trigger_migration_in")).ok  # not in the break
    assert (await s.woz("trigger_migration_out")).ok
    await s.until_phase("ROBOT_WAKE")
    assert not (await s.woz("trigger_migration_out")).ok
    assert (await s.woz("trigger_migration_in")).ok
    await s.until_phase("RETURN")
    await s.woz("end_session")
    await task
    assert "MIGRATE_IN" in s.phases()


async def test_games_commands(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    assert not (await s.woz("start_game", game="quick_draw")).ok  # not in the break
    assert not (await s.woz("end_game")).ok
    await s.woz("goto_phase", phase="CHAT")
    await s.until_phase("CHAT")
    unknown = await s.woz("start_game", game="chess")
    assert not unknown.ok and "quick_draw" in (unknown.error or "")
    for unbuilt in ("staring", "rps_arms", "crocodile_human"):  # M6: a clear error, no game
        refused = await s.woz("start_game", game=unbuilt)
        assert not refused.ok and "not built yet" in (refused.error or "")
        assert "crocodile_robot, quick_draw" in (refused.error or "")
    assert s.ctl.state.phase == "CHAT" and s.ctl.state.chosen_game is None
    assert (await s.woz("start_game", game="quick_draw")).ok
    await s.until_phase("GAME_CHOSEN")
    assert (await s.woz("end_game")).ok
    await s.until_phase("ROBOT_GOODBYE")
    await s.woz("end_session")
    await task
    start = s.data("game_start")[0]
    assert start["game"] == "quick_draw" and start["placeholder"] is False
    assert s.data("game_end")[0]["result"] == "interrupted"
    refusals = [d for d in s.data("woz_action") if d["command"] == "start_game" and not d["ok"]]
    assert len(refusals) == 5  # every refused command is logged with its error


async def test_say_and_say_text(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    missing = await s.woz("say", line_id="no_such_line")
    assert not missing.ok
    needs_name = await s.woz("say", line_id="robot_wake")
    assert not needs_name.ok and "name" in (needs_name.error or "")
    assert (await s.woz("say", line_id="stt_retry", reason="participant_confused")).ok
    assert (await s.woz("say_text", text="Take   your time!")).ok
    await settle(s, 1)
    await s.woz("end_session")
    await task
    woz_turns = [d for d in s.data("turn") if d.get("source") == "woz"]
    assert [t["text"] for t in woz_turns] == ["Sorry, could you say that again?", "Take your time!"]
    assert woz_turns[0]["line_id"] == "stt_retry"
    assert any(isinstance(m, Turn) and m.text == "Take your time!" for m in s.pushed)
    # no active body yet (SETUP): spoken on the laptop speaker
    assert s.speaker.played


async def test_body_commands(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    assert not (await s.woz("set_eyes", state="happy")).ok  # no active body yet
    assert (await s.woz("set_eyes", state="happy", body="fake_robot")).ok
    assert not (await s.woz("set_eyes", state="happy", body="alpha_mini")).ok
    assert (await s.woz("play_motion", name="wave", body="desktop_pet")).ok
    assert ("eyes", "happy") in s.robot.calls
    assert ("motion", "wave") in s.pet.calls
    s.robot.connected = False
    failed = await s.woz("set_eyes", state="sad", body="fake_robot")
    assert not failed.ok and "not connected" in (failed.error or "")


async def test_switch_robot_body(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    real = FakeBody(name="alpha_mini")
    pet, fake = FakeBody(name="desktop_pet"), FakeBody(name="fake_robot")
    s = waiting(
        dev_config,
        dialogue_content,
        tmp_path,
        bodies={"desktop_pet": pet, "fake_robot": fake, "alpha_mini": real},
    )
    task = s.start()
    assert (await s.woz("switch_robot_body", body="fake")).ok  # already fake: no-op
    await s.woz("goto_phase", phase="CHAT")
    await s.until_phase("CHAT")
    assert (await s.woz("switch_robot_body", body="real", reason="demo")).ok
    assert s.ctl.bodies.active_name == "alpha_mini"
    assert ("deactivate", "sleep") in fake.calls and ("activate", "wake_up") in real.calls
    assert s.ctl.snapshot().active_body == "alpha_mini"
    await s.woz("end_session")
    await task
    assert s.data("cue_change")[0] == {
        "cue": "robot_body",
        "old": "fake_robot",
        "new": "alpha_mini",
    }
    switch = [d for d in s.data("migration") if d["direction"] == "robot_switch"]
    assert switch[0]["success"] is True


async def test_switch_to_a_missing_body_is_refused(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    outcome = await s.woz("switch_robot_body", body="real")
    assert not outcome.ok and "alpha_mini" in (outcome.error or "")


# --- pause / emergency stop --------------------------------------------------------------------


async def test_pause_freezes_timers_and_listening(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    assert not (await s.woz("resume")).ok  # not paused
    await s.woz("goto_phase", phase="FOCUS")
    await s.until_phase("FOCUS")
    await settle(s, 10)
    assert (await s.woz("pause")).ok
    assert not (await s.woz("pause")).ok
    remaining = s.ctl.state.phase_timer.remaining_s  # type: ignore[union-attr]
    await settle(s, 120)  # two virtual minutes while paused
    assert s.ctl.state.phase == "FOCUS"
    assert s.ctl.state.phase_timer.remaining_s == pytest.approx(remaining)  # type: ignore[union-attr]
    assert s.ctl.snapshot().paused is True
    asked = s.user.asked
    await settle(s, 30)
    assert s.user.asked == asked  # not listening while paused
    assert (await s.woz("resume")).ok
    await s.until_phase("MIGRATE_OUT")
    await s.woz("end_session")
    await task
    assert any(isinstance(m, StateUpdate) and m.paused for m in s.pushed)
    assert s.ctl.state.phase_durations_s["FOCUS"] > 150  # wall time includes the pause


async def test_emergency_stop_then_resume_restarts_the_phase(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    await s.woz("goto_phase", phase="FOCUS")
    await s.until_phase("FOCUS")
    await settle(s, 5)
    stops_before = s.speaker.stops
    assert (await s.woz("emergency_stop", reason="technical_failure")).ok
    await settle(s)
    assert s.ctl.state.halted and s.ctl.snapshot().paused
    assert s.speaker.stops > stops_before
    assert ("stop", None) in s.pet.calls and ("stop", None) in s.robot.calls  # stop_all
    assert ("speak", "") not in s.pet.calls  # the old workaround is only the fallback
    assert any(isinstance(m, Alert) and m.level == "error" for m in s.pushed)
    await settle(s, 100)
    assert s.ctl.state.phase == "FOCUS"  # frozen, nothing runs
    assert (await s.woz("resume")).ok
    await settle(s)
    assert not s.ctl.state.halted
    restart = s.data("phase_change")[-1]
    assert restart["from"] == "FOCUS" and restart["to"] == "FOCUS" and restart["trigger"] == "woz"
    await s.woz("end_session")
    await task


async def test_emergency_stop_then_end_session(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    task = s.start()
    await s.woz("start_session")
    await s.until_phase("PERSONA_PICK")
    await s.woz("emergency_stop", reason="technical_failure")
    await s.woz("end_session")
    summary = await task
    assert summary["end_reason"] == "completed" and s.phases()[-1] == "END"


# --- state pushes ------------------------------------------------------------------------------


async def test_state_updates_are_pushed_and_listeners_can_leave(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path)
    late: list[Any] = []
    unsubscribe = s.ctl.subscribe(late.append)

    def broken(_: Any) -> None:
        raise RuntimeError("panel gone")

    s.ctl.subscribe(broken)
    task = s.start()
    await s.woz("goto_phase", phase="FOCUS")
    await s.until_phase("FOCUS")
    unsubscribe()
    count = len(late)
    await s.woz("end_session")
    await task
    assert len(late) == count  # unsubscribed
    phases = [m.phase for m in s.pushed if isinstance(m, StateUpdate)]
    assert "FOCUS" in phases and phases[-1] == "END"
    focus = next(
        m for m in s.pushed if isinstance(m, StateUpdate) and m.timer and m.timer.name == "focus"
    )
    assert focus.active_body == "desktop_pet" and focus.timer.total_s == 30  # type: ignore[union-attr]
    assert s.data("woz_listener_error")  # the broken listener was dropped and logged


# --- terminal commands -------------------------------------------------------------------------


def test_terminal_commands_become_woz_commands() -> None:
    goto = parse_terminal_command("/goto chat")
    assert isinstance(goto, WozCommand) and goto.args == {"phase": "CHAT"}
    assert goto.reason == "other" and goto.note
    extend = parse_terminal_command("/extend 30")
    assert isinstance(extend, WozCommand) and extend.args == {"seconds": 30.0}
    assert validate_command(extend) is None
    stop = parse_terminal_command("/stop")
    assert isinstance(stop, WozCommand) and stop.command == "emergency_stop"
    assert parse_terminal_command("/help") == HELP
    assert "number" in str(parse_terminal_command("/extend lots"))
    assert "needs a value" in str(parse_terminal_command("/goto"))
    assert "unknown" in str(parse_terminal_command("/dance"))


async def test_missing_configured_robot_body_is_reported_at_start(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = waiting(dev_config, dialogue_content, tmp_path, robot={"body": "alpha_mini"})
    task = s.start()
    await s.woz("end_session")
    await task
    alert = s.data("alert")[0]
    assert alert["level"] == "warning" and "alpha_mini" in alert["message"]
    assert "fake_robot" in alert["message"]


async def test_a_session_interrupted_twice_still_writes_its_summary(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    # Ctrl+C, and a second Ctrl+C while the background work is still stopping: the study log
    # must get its session_end and summary.json anyway.
    s = waiting(dev_config, dialogue_content, tmp_path)
    run = s.start()
    await settle(s)
    cleanup_done = asyncio.Event()

    async def slow_to_stop() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.shield(cleanup_done.wait())

    s.ctl.spawn(slow_to_stop())
    await settle(s)

    run.cancel()
    await settle(s)  # the session now waits for the background work to stop
    run.cancel()
    await settle(s)
    cleanup_done.set()
    await asyncio.wait([run], timeout=1)

    assert run.cancelled()
    assert (s.logger.folder / "summary.json").exists()
    assert [e["type"] for e in s.logger.read_events()][-1] == "session_end"
