"""Export a session's events as ``timeline.csv`` for analysis (docs/LOGGING_AND_STUDY.md §6).

Run (from ``brain/``):

    python -m pipi_brain.tools.export_timeline ../logs/P03_20261202-101200
    python -m pipi_brain.tools.export_timeline ../logs/P03_20261202-101200 --all

Reads ``events.jsonl`` from the session folder and writes ``timeline.csv`` next to it (one row
per event: seconds since start, wall clock, phase, body, event type, a short text, latency) so
the team can merge it with the observation sheet and the interview notes in Excel or Google
Sheets. By default the very frequent low-level rows (``body_message``, ``woz_command``,
``woz_ack``) are left out; ``--all`` keeps every event. Nothing is invented: a missing field
stays empty. ``memory.json`` (it holds the participant's first name) is never read; the events
already carry the name as ``[NAME]``. A corrupt line is skipped and counted, not fatal.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

EVENTS_FILE = "events.jsonl"
OUTPUT_FILE = "timeline.csv"
HEADER = ("t_rel_s", "clock", "phase", "body", "event", "text", "latency_ms")
NOISE_TYPES = frozenset({"body_message", "woz_command", "woz_ack"})
MAX_SUMMARY_CHARS = 120
ELLIPSIS = "…"

Event = Mapping[str, Any]
Data = Mapping[str, Any]


class TimelineError(Exception):
    """The session folder cannot be exported (missing folder or events file)."""


@dataclass(frozen=True)
class ExportResult:
    path: Path
    rows: int
    left_out: int
    corrupt: int


# --- small value helpers ---------------------------------------------------------------------


def _s(value: Any) -> str:
    """A field as text; a missing field (None) stays empty."""
    return "" if value is None else str(value)


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _compact(value: Any) -> str:
    if isinstance(value, Mapping | list | tuple):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return str(value)


def _cut(text: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - len(ELLIPSIS)] + ELLIPSIS


def _key_values(data: Data) -> str:
    return _cut(", ".join(f"{key}={_compact(value)}" for key, value in data.items()))


def _join(parts: Sequence[str | None]) -> str:
    return ", ".join(part for part in parts if part)


def _labelled(label: str, value: Any) -> str | None:
    return None if value is None or value == "" else f"{label}{value}"


# --- text per event type ---------------------------------------------------------------------


def _turn(d: Data) -> str:
    return f"{_s(d.get('speaker'))}: {_s(d.get('text'))}"


def _phase_change(d: Data) -> str:
    extras = _join([_s(d.get(k)) for k in ("trigger", "command", "reason")])
    extras = _join([extras, _labelled("via ", d.get("via"))])
    base = f"{_s(d.get('from'))} -> {_s(d.get('to'))}"
    return f"{base} ({extras})" if extras else base


def _migration(d: Data) -> str:
    head = f"{_s(d.get('direction'))} {_s(d.get('stage'))}"
    stage = d.get("stage")
    if stage == "start":
        return f"{head}: {_s(d.get('from'))} -> {_s(d.get('to'))}"
    if stage == "skipped":
        return f"{head}: {_s(d.get('reason'))}"
    if stage != "end":
        return head
    success = {True: "success", False: "FAILED"}.get(d.get("success"))
    duration = _number(d.get("duration_ms"))
    return f"{head}: " + _join(
        [
            success,
            _labelled("fallback ", d.get("fallback")),
            _labelled("error ", d.get("error")),
            None if duration is None else f"{duration} ms",
        ]
    )


def _game_start(d: Data) -> str:
    rounds = d.get("rounds_planned")
    details = _join(
        [
            _labelled("mode ", d.get("mode")),
            None if rounds is None else f"{rounds} rounds planned",
            _labelled("fallback ", d.get("fallback")),
        ]
    )
    return f"{_s(d.get('game'))} start: {details}"


def _game_round(d: Data) -> str:
    text = f"{_s(d.get('game'))} round {_s(d.get('round'))}: {_s(d.get('result'))}"
    if d.get("winner"):
        text += f" (winner {d['winner']})"
    if d.get("fallback"):
        text += f" [fallback {d['fallback']}]"
    return text


def _game_end(d: Data) -> str:
    rounds = d.get("rounds")
    details = _join([_s(d.get("result")), None if rounds is None else f"{rounds} rounds"])
    return f"{_s(d.get('game'))} end: {details}"


def _game_choice(d: Data) -> str:
    text = f"heard '{_s(d.get('heard'))}' -> {_s(d.get('game'))} ({_s(d.get('method'))})"
    extras = _join(
        [
            _labelled("action ", d.get("action")),
            _labelled("after round ", d.get("after_round")),
            "not available" if d.get("available") is False else None,
        ]
    )
    return _join([text, extras])


def _woz_action(d: Data) -> str:
    args = d.get("args")
    return _join(
        [
            _s(d.get("command")),
            _key_values(args) if isinstance(args, Mapping) and args else None,
            _labelled("reason: ", d.get("reason")),
            _labelled("note: ", d.get("free_text")),
            f"FAILED: {_s(d.get('error'))}" if d.get("ok") is False else None,
        ]
    )


def _alert(d: Data) -> str:
    return f"{_s(d.get('level')).upper()}: {_s(d.get('message'))}"


def _silence_reprompt(d: Data) -> str:
    return f"waited {_s(d.get('waited_s'))} s -> {_s(d.get('action'))}"


def _clarification(d: Data) -> str:
    return _s(d.get("reason")) or _key_values(d)


def _memory_reference(d: Data) -> str:
    what = d.get("what")
    shown = "/".join(map(str, what)) if isinstance(what, list) else _s(what)
    return _join([shown, _labelled("body ", d.get("body"))])


def _persona_choice(d: Data) -> str:
    return f"{_s(d.get('persona'))} ({_s(d.get('method'))})"


def _focus_precue(d: Data) -> str:
    remaining = _number(d.get("remaining_s"))
    left = _s(d.get("remaining_s")) if remaining is None else f"{remaining:.1f}"
    return f"{_s(d.get('motion'))}, {left} s left"


def _cue_change(d: Data) -> str:
    return f"{_s(d.get('cue'))}: {_s(d.get('old'))} -> {_s(d.get('new'))}"


def _error(d: Data) -> str:
    prefix = d.get("message_type") or d.get("purpose") or d.get("remote")
    error = _s(d.get("error"))
    return f"{prefix}: {error}" if prefix else error


def _session_start(d: Data) -> str:
    personas = d.get("persona_options")
    return _join(
        [
            _labelled("mode ", d.get("mode")),
            _labelled("runner ", d.get("runner")),
            "personas " + "/".join(map(str, personas)) if isinstance(personas, list) else None,
        ]
    )


def _session_end(d: Data) -> str:
    duration = _number(d.get("duration_ms"))
    turns = d.get("user_turns")
    return _join(
        [
            _labelled("reason ", d.get("reason")),
            None if duration is None else f"{duration / 1000:.1f} s",
            None if turns is None else f"{turns} user turns",
        ]
    )


FORMATTERS: Mapping[str, Callable[[Data], str]] = {
    "turn": _turn,
    "phase_change": _phase_change,
    "migration": _migration,
    "game_start": _game_start,
    "game_round": _game_round,
    "game_end": _game_end,
    "game_choice": _game_choice,
    "woz_action": _woz_action,
    "alert": _alert,
    "silence_reprompt": _silence_reprompt,
    "clarification": _clarification,
    "memory_reference": _memory_reference,
    "persona_choice": _persona_choice,
    "focus_precue": _focus_precue,
    "cue_change": _cue_change,
    "body_error": _error,
    "stt_error": _error,
    "llm_error": _error,
    "tts_error": _error,
    "session_start": _session_start,
    "session_end": _session_end,
}


def event_text(event: Event) -> str:
    """A short human-readable summary of the event's data (never changes the event)."""
    data = event.get("data")
    if not isinstance(data, Mapping):
        return "" if data is None else _cut(_compact(data))
    formatter = FORMATTERS.get(_s(event.get("type")))
    return formatter(data) if formatter else _key_values(data)


def event_latency_ms(event: Event) -> int | float | None:
    """turn: total_ms; migration end: duration_ms; game_round: timings.round_ms; else None."""
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    kind = event.get("type")
    if kind == "turn":
        return _number(data.get("total_ms"))
    if kind == "migration" and data.get("stage") == "end":
        return _number(data.get("duration_ms"))
    if kind == "game_round":
        timings = data.get("timings")
        return _number(timings.get("round_ms")) if isinstance(timings, Mapping) else None
    return None


# --- reading and writing ---------------------------------------------------------------------


def _parse_line(raw: bytes) -> dict[str, Any] | None:
    """One event, or None when the line is corrupt (bad UTF-8, bad JSON, not an object)."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    """All events in file order, plus the number of corrupt lines skipped (blank lines ignored)."""
    events: list[dict[str, Any]] = []
    corrupt = 0
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            event = _parse_line(raw)
            if event is None:
                corrupt += 1
            else:
                events.append(event)
    return events, corrupt


def _t_rel_s(value: Any) -> str:
    ms = _number(value)
    return "" if ms is None else f"{ms / 1000:.1f}"


def _clock(ts: Any) -> str:
    """Wall time HH:MM:SS as logged (the laptop's local time with its offset)."""
    try:
        return datetime.fromisoformat(str(ts)).strftime("%H:%M:%S")
    except ValueError:
        return ""


def to_row(event: Event) -> list[str]:
    return [
        _t_rel_s(event.get("t_rel_ms")),
        _clock(event.get("ts")) if event.get("ts") else "",
        _s(event.get("phase")),
        _s(event.get("body")),
        _s(event.get("type")),
        event_text(event),
        _s(event_latency_ms(event)),
    ]


def export_timeline(folder: Path, *, include_all: bool = False) -> ExportResult:
    """Write ``folder/timeline.csv`` (overwriting it) from ``folder/events.jsonl``."""
    if not folder.is_dir():
        raise TimelineError(f"session folder not found: {folder}")
    events_path = folder / EVENTS_FILE
    if not events_path.is_file():
        raise TimelineError(f"no {EVENTS_FILE} in {folder} (is this a session folder?)")
    events, corrupt = read_events(events_path)
    kept = [e for e in events if include_all or e.get("type") not in NOISE_TYPES]
    out_path = folder / OUTPUT_FILE
    # utf-8-sig: the BOM makes Excel read accents correctly; newline="" per the csv docs.
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(to_row(event) for event in kept)
    return ExportResult(out_path, len(kept), len(events) - len(kept), corrupt)


# --- command line ----------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_timeline", description=__doc__.split("\n")[0])
    parser.add_argument("session_folder", type=Path, help="e.g. ../logs/P03_20261202-101200")
    parser.add_argument(
        "--all",
        dest="include_all",
        action="store_true",
        help="include every event (also body_message, woz_command, woz_ack)",
    )
    args = parser.parse_args(argv)
    try:
        result = export_timeline(args.session_folder, include_all=args.include_all)
    except (TimelineError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if result.corrupt:
        print(
            f"Warning: skipped {result.corrupt} corrupt line(s) in {EVENTS_FILE}", file=sys.stderr
        )
    print(f"Wrote {result.path} ({result.rows} rows)")
    if result.left_out:
        kinds = ", ".join(sorted(NOISE_TYPES))
        print(f"Left out {result.left_out} low-level rows ({kinds}); --all includes them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
