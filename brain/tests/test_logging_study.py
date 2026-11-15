"""JSONL study logger, latency stats, timed calls."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pipi_brain.latency import TurnLatency, summarize, summarize_turns
from pipi_brain.logging_study import LoggerError, StudyLogger
from pipi_brain.resilience import describe_error, redact_secrets, timed_call

FIXED_NOW = datetime(2026, 12, 2, 10, 15, 3, 412000, tzinfo=timezone(timedelta(hours=1)))


def _logger(tmp_path: Path, participant: str = "P03") -> StudyLogger:
    ticks = iter([100.0, 100.5, 101.0, 102.0, 103.0])
    return StudyLogger(tmp_path, participant, monotonic=lambda: next(ticks), now=lambda: FIXED_NOW)


def test_session_folder_and_event_format(tmp_path: Path) -> None:
    logger = _logger(tmp_path)
    assert logger.session_id == "P03_20261202-101503"
    assert logger.folder == tmp_path / "P03_20261202-101503"
    event = logger.log("turn", {"speaker": "user", "text": "hi"}, phase="CHAT", body="terminal")
    line = json.loads(logger.events_path.read_text(encoding="utf-8").splitlines()[0])
    assert line == event
    assert line["ts"] == "2026-12-02T10:15:03.412+01:00"
    assert line["t_rel_ms"] == 500
    assert (line["session"], line["phase"], line["body"], line["type"]) == (
        "P03_20261202-101503",
        "CHAT",
        "terminal",
        "turn",
    )
    assert line["data"] == {"speaker": "user", "text": "hi"}


def test_events_are_appended_one_per_line(tmp_path: Path) -> None:
    logger = _logger(tmp_path)
    logger.log("a")
    logger.log("b", {"x": 1})
    assert [e["type"] for e in logger.read_events()] == ["a", "b"]


def test_two_sessions_in_the_same_second_get_separate_folders(tmp_path: Path) -> None:
    first, second = _logger(tmp_path), _logger(tmp_path)
    assert first.folder != second.folder
    assert second.folder.name.endswith("-2")


@pytest.mark.parametrize("bad_id", ["", "../evil", "P 01", "a" * 33, "Lena Müller"])
def test_participant_id_must_be_pseudonymous_and_safe(tmp_path: Path, bad_id: str) -> None:
    with pytest.raises(LoggerError):
        StudyLogger(tmp_path, bad_id)


def test_write_json_snapshot(tmp_path: Path) -> None:
    logger = _logger(tmp_path)
    path = logger.write_json("memory.json", {"name": "Lena"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"name": "Lena"}
    assert not list(logger.folder.glob("*.tmp"))


def test_latency_format_and_summary() -> None:
    assert TurnLatency(640, 910, 520, 2101).format() == (
        "stt 640 ms | llm 910 ms | tts 520 ms | total 2101 ms"
    )
    assert TurnLatency(None, 900, None, 950).format() == "stt - | llm 900 ms | tts - | total 950 ms"
    stats = summarize([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])
    assert stats == {"count": 10, "mean": 550.0, "p50": 550.0, "p90": 900, "max": 1000}
    assert summarize([])["count"] == 0
    turns = summarize_turns([TurnLatency(None, 10, 20, 40), TurnLatency(5, 10, None, 30)])
    assert turns["stt_ms"]["count"] == 1 and turns["total_ms"]["max"] == 40


async def test_timed_call_success_error_and_timeout() -> None:
    async def ok() -> int:
        return 42

    async def boom() -> int:
        raise ValueError("bad input")

    async def slow() -> int:
        await asyncio.sleep(1)
        return 1

    good = await timed_call(ok, 1.0)
    assert good.ok and good.value == 42
    failed = await timed_call(boom, 1.0)
    assert not failed.ok and failed.error == "ValueError: bad input" and not failed.timed_out
    late = await timed_call(slow, 0.01)
    assert late.timed_out and late.error == "timeout after 0.01 s"


def test_secrets_are_redacted_from_error_texts() -> None:
    assert redact_secrets("key sk-proj-AbC123xyz_-9 rejected") == "key sk-*** rejected"
    assert "sk-abcdefgh" not in describe_error(RuntimeError("bad key sk-abcdefgh"))
