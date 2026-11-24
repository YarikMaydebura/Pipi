"""The timeline export: a session's events.jsonl -> timeline.csv (no network, tmp folders)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from pipi_brain.tools.export_timeline import (
    HEADER,
    event_latency_ms,
    event_text,
    export_timeline,
    main,
    read_events,
)

SESSION = "P01_20261202-101200"


def make_event(
    type_: str,
    data: dict[str, Any],
    *,
    t_rel_ms: int = 1000,
    ts: str = "2026-12-02T10:15:03.412+01:00",
    phase: str | None = "CHAT",
    body: str | None = "desktop_pet",
) -> dict[str, Any]:
    return {
        "ts": ts,
        "t_rel_ms": t_rel_ms,
        "session": SESSION,
        "phase": phase,
        "body": body,
        "type": type_,
        "data": data,
    }


def write_session(tmp_path: Path, lines: list[str]) -> Path:
    folder = tmp_path / SESSION
    folder.mkdir()
    (folder / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def as_lines(*events: dict[str, Any]) -> list[str]:
    return [json.dumps(event) for event in events]


def read_csv(folder: Path) -> list[list[str]]:
    with (folder / "timeline.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


START = make_event("session_start", {"mode": "study", "persona_options": ["cheerful", "calm"]})
USER_TURN = make_event(
    "turn",
    {"speaker": "user", "text": "I'm [NAME], hi!", "stt_ms": 400, "total_ms": 2345},
    t_rel_ms=12345,
)
BODY_MESSAGE = make_event("body_message", {"direction": "out", "type": "speak"})
WOZ_COMMAND = make_event("woz_command", {"command": "say", "reason": "timing"})
WOZ_ACK = make_event("woz_ack", {"command": "say", "ok": True, "elapsed_ms": 14})


# --- reading ---------------------------------------------------------------------------------


def test_read_events_skips_blank_and_counts_corrupt_lines(tmp_path: Path) -> None:
    # Arrange
    lines = [*as_lines(START), "", "{not json", "[1, 2]", *as_lines(USER_TURN), "   "]
    folder = write_session(tmp_path, lines)

    # Act
    events, corrupt = read_events(folder / "events.jsonl")

    # Assert
    assert [e["type"] for e in events] == ["session_start", "turn"]
    assert corrupt == 2


# --- text per event type ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_", "data", "expected"),
    [
        ("turn", {"speaker": "pipi", "text": "Hiya!"}, "pipi: Hiya!"),
        (
            "phase_change",
            {"from": "SETUP", "to": "CHAT", "trigger": "auto"},
            "SETUP -> CHAT (auto)",
        ),
        (
            "phase_change",
            {"from": "CHAT", "to": "FOCUS", "trigger": "woz", "command": "goto", "reason": "stuck"},
            "CHAT -> FOCUS (woz, goto, stuck)",
        ),
        (
            "migration",
            {"direction": "out", "stage": "start", "from": "desktop_pet", "to": "fake_robot"},
            "out start: desktop_pet -> fake_robot",
        ),
        (
            "migration",
            {"direction": "out", "stage": "end", "success": True, "duration_ms": 6353},
            "out end: success, 6353 ms",
        ),
        (
            "migration",
            {
                "direction": "in",
                "stage": "end",
                "success": False,
                "fallback": "stay_on_pet",
                "error": "timeout",
                "duration_ms": 900,
            },
            "in end: FAILED, fallback stay_on_pet, error timeout, 900 ms",
        ),
        ("migration", {"direction": "in", "stage": "skipped", "reason": "no robot"}, None),
        (
            "game_start",
            {"game": "quick_draw", "mode": "typed", "rounds_planned": 3, "fallback": "typed"},
            "quick_draw start: mode typed, 3 rounds planned, fallback typed",
        ),
        (
            "game_round",
            {"game": "crocodile_robot", "round": 1, "result": "guessed", "winner": "participant"},
            "crocodile_robot round 1: guessed (winner participant)",
        ),
        (
            "game_end",
            {"game": "crocodile_robot", "result": "completed", "rounds": 2},
            "crocodile_robot end: completed, 2 rounds",
        ),
        (
            "game_choice",
            {"heard": "the duel one", "game": "quick_draw", "method": "llm"},
            "heard 'the duel one' -> quick_draw (llm)",
        ),
        (
            "woz_action",
            {"command": "say", "reason": "timing", "free_text": "ggg", "ok": True},
            "say, reason: timing, note: ggg",
        ),
        ("alert", {"level": "warning", "message": "robot lost"}, "WARNING: robot lost"),
        ("silence_reprompt", {"waited_s": 12, "action": "reprompt"}, "waited 12 s -> reprompt"),
        ("clarification", {"reason": "low confidence"}, "low confidence"),
        ("memory_reference", {"what": ["game_events"], "body": "fake_robot"}, None),
        ("persona_choice", {"persona": "calm", "method": "voice"}, "calm (voice)"),
        ("focus_precue", {"motion": "yawn", "remaining_s": 9.998}, "yawn, 10.0 s left"),
        ("cue_change", {"cue": "robot_body", "old": "a", "new": "b"}, "robot_body: a -> b"),
        (
            "body_error",
            {"message_type": "speak", "error": "no ack", "timed_out": True},
            "speak: no ack",
        ),
        ("stt_error", {"error": "TimeoutError", "retry": True}, "TimeoutError"),
        (
            "llm_error",
            {"error": "LlmError: x", "purpose": "guess_judge"},
            "guess_judge: LlmError: x",
        ),
        ("tts_error", {"error": "boom"}, "boom"),
        (
            "session_start",
            {"mode": "study", "persona_options": ["cheerful", "calm"]},
            "mode study, personas cheerful/calm",
        ),
    ],
)
def test_event_text_per_type(type_: str, data: dict[str, Any], expected: str | None) -> None:
    text = event_text(make_event(type_, data))

    if expected is None:  # only check that the important values are there
        for value in data.values():
            shown = value[0] if isinstance(value, list) else value
            assert str(shown) in text
    else:
        assert text == expected


def test_session_end_text_has_reason_and_duration() -> None:
    text = event_text(make_event("session_end", {"reason": "interrupted", "duration_ms": 431532}))

    assert "interrupted" in text
    assert "431.5 s" in text


def test_unknown_event_gets_compact_key_value_summary_cut_to_length() -> None:
    short = event_text(make_event("health_check", {"desktop_pet": "ok", "robot": None}))
    long = event_text(make_event("tts_prewarm", {"lines": "x" * 500}))

    assert short == "desktop_pet=ok, robot=None"
    assert len(long) <= 120
    assert long.endswith("…")


def test_event_text_does_not_change_the_event() -> None:
    event = make_event("game_round", {"game": "g", "round": 1, "timings": {"round_ms": 5}})
    before = json.dumps(event, sort_keys=True)

    event_text(event)
    event_latency_ms(event)

    assert json.dumps(event, sort_keys=True) == before


# --- latency ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_", "data", "expected"),
    [
        ("turn", {"speaker": "user", "text": "hi", "total_ms": 2345}, 2345),
        ("turn", {"speaker": "pipi", "text": "hi", "tts_ms": 7}, None),
        ("migration", {"direction": "out", "stage": "end", "duration_ms": 6353}, 6353),
        ("migration", {"direction": "out", "stage": "start"}, None),
        ("game_round", {"game": "g", "round": 1, "timings": {"round_ms": 17531}}, 17531),
        ("game_round", {"game": "g", "round": 1, "timings": {}}, None),
        ("game_end", {"game": "g", "duration_ms": 40000}, None),
        ("alert", {"level": "info", "message": "x"}, None),
    ],
)
def test_event_latency_ms(type_: str, data: dict[str, Any], expected: int | None) -> None:
    assert event_latency_ms(make_event(type_, data)) == expected


# --- the csv ---------------------------------------------------------------------------------


def test_export_writes_header_bom_and_rows(tmp_path: Path) -> None:
    # Arrange
    folder = write_session(tmp_path, as_lines(START, USER_TURN))

    # Act
    result = export_timeline(folder)

    # Assert
    raw = (folder / "timeline.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = read_csv(folder)
    assert rows[0] == list(HEADER)
    assert rows[0] == ["t_rel_s", "clock", "phase", "body", "event", "text", "latency_ms"]
    assert rows[2] == [
        "12.3",
        "10:15:03",
        "CHAT",
        "desktop_pet",
        "turn",
        "user: I'm [NAME], hi!",
        "2345",
    ]
    assert rows[1][-1] == ""
    assert result.rows == 2
    assert result.path == folder / "timeline.csv"


def test_export_keeps_accents_and_empty_phase_and_body(tmp_path: Path) -> None:
    event = make_event("turn", {"speaker": "user", "text": "Très café"}, phase=None, body=None)
    folder = write_session(tmp_path, as_lines(event))

    export_timeline(folder)

    row = read_csv(folder)[1]
    assert row[2:6] == ["", "", "turn", "user: Très café"]


def test_export_leaves_out_low_level_rows_by_default(tmp_path: Path) -> None:
    folder = write_session(tmp_path, as_lines(START, BODY_MESSAGE, WOZ_COMMAND, WOZ_ACK, USER_TURN))

    result = export_timeline(folder)

    assert [row[4] for row in read_csv(folder)[1:]] == ["session_start", "turn"]
    assert result.rows == 2
    assert result.left_out == 3


def test_export_with_all_keeps_every_event(tmp_path: Path) -> None:
    folder = write_session(tmp_path, as_lines(START, BODY_MESSAGE, WOZ_COMMAND, WOZ_ACK, USER_TURN))

    result = export_timeline(folder, include_all=True)

    assert result.rows == 5
    assert result.left_out == 0


def test_export_overwrites_an_existing_timeline(tmp_path: Path) -> None:
    folder = write_session(tmp_path, as_lines(START))
    (folder / "timeline.csv").write_text("old,stuff\n1,2\n3,4\n", encoding="utf-8")

    export_timeline(folder)

    assert len(read_csv(folder)) == 2


def test_export_never_reads_memory_json(tmp_path: Path) -> None:
    folder = write_session(tmp_path, as_lines(START, USER_TURN))
    (folder / "memory.json").write_text(json.dumps({"name": "Zelda"}), encoding="utf-8")

    export_timeline(folder)

    assert "Zelda" not in (folder / "timeline.csv").read_text(encoding="utf-8-sig")


# --- command line ----------------------------------------------------------------------------


def test_main_prints_path_and_row_count_and_reports_corrupt_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = write_session(tmp_path, [*as_lines(START), "{broken", *as_lines(USER_TURN)])

    code = main([str(folder)])

    out, err = capsys.readouterr()
    assert code == 0
    assert str(folder / "timeline.csv") in out
    assert "2 rows" in out
    assert "1 corrupt line" in err


def test_main_all_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = write_session(tmp_path, as_lines(START, BODY_MESSAGE))

    code = main([str(folder), "--all"])

    assert code == 0
    assert "2 rows" in capsys.readouterr().out


def test_main_missing_folder_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path / "nope")])

    assert code == 2
    assert "not found" in capsys.readouterr().err.lower()


def test_main_missing_events_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "empty_session").mkdir()

    code = main([str(tmp_path / "empty_session")])

    assert code == 2
    assert "events.jsonl" in capsys.readouterr().err
    assert not (tmp_path / "empty_session" / "timeline.csv").exists()
