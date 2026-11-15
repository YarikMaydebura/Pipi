"""Per-turn latency numbers (docs/SYSTEM_DESIGN.md section 8) and summary statistics."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class TurnLatency:
    """Milliseconds per step. ``None`` = step did not run (e.g. typed input has no STT).

    ``total_ms`` runs from the moment the end of the user's speech was detected (or the typed
    line arrived) until Pipi's audio starts (or the caption is shown if there is no audio).
    The participant additionally waits ``vad.end_silence_ms`` before that end is detected.
    """

    stt_ms: int | None
    llm_ms: int | None
    tts_ms: int | None
    total_ms: int

    def format(self) -> str:
        def part(label: str, value: int | None) -> str:
            return f"{label} {value} ms" if value is not None else f"{label} -"

        return " | ".join(
            [
                part("stt", self.stt_ms),
                part("llm", self.llm_ms),
                part("tts", self.tts_ms),
                part("total", self.total_ms),
            ]
        )


def summarize(values: Sequence[int]) -> dict[str, float | int | None]:
    """count / mean / median / p90 / max of a list of milliseconds (empty list -> Nones)."""
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p90": None, "max": None}
    ordered = sorted(values)
    p90_index = max(0, round(0.9 * len(ordered)) - 1)
    return {
        "count": len(ordered),
        "mean": round(statistics.fmean(ordered), 1),
        "p50": statistics.median(ordered),
        "p90": ordered[p90_index],
        "max": ordered[-1],
    }


def summarize_turns(latencies: Sequence[TurnLatency]) -> dict[str, dict[str, float | int | None]]:
    def present(values: Sequence[int | None]) -> list[int]:
        return [v for v in values if v is not None]

    return {
        "stt_ms": summarize(present([t.stt_ms for t in latencies])),
        "llm_ms": summarize(present([t.llm_ms for t in latencies])),
        "tts_ms": summarize(present([t.tts_ms for t in latencies])),
        "total_ms": summarize([t.total_ms for t in latencies]),
    }
