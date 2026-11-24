"""JSONL study logger (docs/LOGGING_AND_STUDY.md).

One folder per session: ``<log_dir>/<participant_id>_<YYYYMMDD-HHMMSS>/`` containing
``events.jsonl`` (append-only, one event per line, flushed immediately), ``memory.json`` and
``summary.json``. The logger never receives secrets; error texts are redacted upstream.

Privacy (decision Nov 24): the participant's first name lives only in ``memory.json``. Once the
session learns it (``redact_name``), every string in ``events.jsonl`` is written with the name
replaced by ``[NAME]`` (whole words, any case), and the lines written before are rewritten
once, because the participant says the name before Pipi knows it is one.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

# Pseudonymous IDs only (P01, DEV, ...). Also prevents path tricks such as "../x".
PARTICIPANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
EVENTS_FILE = "events.jsonl"
NAME_TOKEN = "[NAME]"
MIN_NAME_CHARS = 2  # a one-letter "name" would blank out ordinary words


class LoggerError(Exception):
    """Raised when the session folder cannot be created."""


def validate_participant_id(participant_id: str) -> str:
    if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
        raise LoggerError(
            f"Invalid participant id {participant_id!r}: use letters, digits, '_' or '-' "
            "(max 32 chars), e.g. P01"
        )
    return participant_id


class StudyLogger:
    def __init__(
        self,
        log_dir: Path,
        participant_id: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        validate_participant_id(participant_id)
        self._monotonic = monotonic
        self._now = now
        self._start = monotonic()
        self.session_id = f"{participant_id}_{now().strftime('%Y%m%d-%H%M%S')}"
        self.folder = self._create_folder(log_dir, self.session_id)
        self.events_path = self.folder / EVENTS_FILE
        self._name_patterns: list[re.Pattern[str]] = []

    # --- privacy -------------------------------------------------------------------------------

    def redact_name(self, name: str | None) -> None:
        """From now on write ``name`` as ``[NAME]``; also rewrite the events written so far."""
        cleaned = (name or "").strip()
        if len(cleaned) < MIN_NAME_CHARS:
            return
        pattern = re.compile(rf"(?<!\w){re.escape(cleaned)}(?!\w)", re.IGNORECASE)
        if any(p.pattern == pattern.pattern for p in self._name_patterns):
            return
        self._name_patterns.append(pattern)
        self._rewrite_events()

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for pattern in self._name_patterns:
                value = pattern.sub(NAME_TOKEN, value)
            return value
        if isinstance(value, Mapping):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._redact(item) for item in value]
        return value

    def _rewrite_events(self) -> None:
        """Redact the lines already on disk (atomic replace, so a crash never loses the log)."""
        if not self.events_path.is_file():
            return
        tmp = self.events_path.with_suffix(".jsonl.tmp")
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
            redacted = [
                json.dumps(self._redact(json.loads(line)), ensure_ascii=False, default=str)
                for line in lines
                if line.strip()
            ]
            tmp.write_text("".join(line + "\n" for line in redacted), encoding="utf-8")
            os.replace(tmp, self.events_path)
        except (OSError, ValueError) as exc:
            print(f"[logger] could not redact the name in earlier events: {exc}", file=sys.stderr)

    @staticmethod
    def _create_folder(log_dir: Path, session_id: str) -> Path:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            for suffix in ("", *(f"-{n}" for n in range(2, 100))):
                folder = log_dir / f"{session_id}{suffix}"
                try:
                    folder.mkdir()
                except FileExistsError:
                    continue
                return folder
        except OSError as exc:
            raise LoggerError(f"Cannot create session log folder in {log_dir}: {exc}") from exc
        raise LoggerError(f"Too many sessions named {session_id} in {log_dir}")

    def log(
        self,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        *,
        phase: str | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        """Append one event and flush it to disk. Returns the event that was written."""
        event = {
            "ts": self._now().isoformat(timespec="milliseconds"),
            "t_rel_ms": round((self._monotonic() - self._start) * 1000),
            "session": self.session_id,
            "phase": phase,
            "body": body,
            "type": event_type,
            "data": self._redact(dict(data or {})),
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        try:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        except OSError as exc:
            # Never crash the session over a log write, but never hide it either.
            print(f"[logger] could not write event {event_type}: {exc}", file=sys.stderr)
        return event

    def write_json(self, file_name: str, data: Mapping[str, Any]) -> Path:
        """Write a JSON snapshot (memory.json, summary.json) atomically."""
        target = self.folder / file_name
        tmp = target.with_suffix(target.suffix + ".tmp")
        text = json.dumps(dict(data), ensure_ascii=False, indent=2, default=str)
        try:
            tmp.write_text(text + "\n", encoding="utf-8")
            os.replace(tmp, target)
        except OSError as exc:
            print(f"[logger] could not write {file_name}: {exc}", file=sys.stderr)
        return target

    def read_events(self) -> list[dict[str, Any]]:
        """All events written so far (used by tests and the summary)."""
        if not self.events_path.is_file():
            return []
        lines = self.events_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
