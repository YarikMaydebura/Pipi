"""Disk cache for the fixed lines' speech, so they play instantly (docs/SYSTEM_DESIGN.md 4.3).

Key = sha256(model, voice, text): changing the voice or the wording makes a new entry.
Files are ``<cache dir>/<key>.wav`` (the text itself is never in a file name). Only FIXED
lines from ``lines.yaml`` are cached; anything with participant data (a name, an LLM answer)
is synthesized live and kept in memory only (privacy: nothing personal on disk).

``prewarm`` synthesizes all fixed lines at session start, in the background, with a total
timeout. Lines that fail are simply synthesized live later (and the failure is reported).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import wave
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipi_brain.resilience import describe_error, timed_call
from pipi_brain.speech.audio_utils import pcm16_to_wav
from pipi_brain.speech.base import SpeechAudio, TextToSpeech

ErrorLog = Callable[[str, Mapping[str, Any]], None]


@dataclass(frozen=True)
class CachedSpeech:
    audio: SpeechAudio | None  # None = synthesis failed (caller falls back to captions)
    from_cache: bool
    elapsed_ms: int
    error: str | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class PrewarmReport:
    lines: int
    already_cached: int
    synthesized: int
    failed: int
    timed_out: bool
    elapsed_ms: int


def cache_key(text: str, *, voice: str, model: str) -> str:
    return hashlib.sha256(f"{model}\x00{voice}\x00{text}".encode()).hexdigest()


class TtsCache:
    def __init__(
        self,
        folder: Path,
        *,
        tts: TextToSpeech,
        model: str,
        voice: str,
        timeout_s: float,
        on_error: ErrorLog,
    ) -> None:
        self._folder = folder
        self._tts = tts
        self._model = model
        self._voice = voice
        self._timeout_s = timeout_s
        self._on_error = on_error

    def path_for(self, text: str) -> Path:
        return self._folder / f"{cache_key(text, voice=self._voice, model=self._model)}.wav"

    def load(self, text: str) -> SpeechAudio | None:
        path = self.path_for(text)
        if not path.is_file():
            return None
        try:
            with wave.open(str(path), "rb") as wav:
                return SpeechAudio(
                    pcm16=wav.readframes(wav.getnframes()), sample_rate=wav.getframerate()
                )
        except (OSError, wave.Error, EOFError) as exc:
            self._on_error("tts_error", {"error": describe_error(exc), "cache": "unreadable"})
            return None

    async def get(self, text: str) -> CachedSpeech:
        start = time.perf_counter()
        cached = self.load(text)
        if cached is not None:
            return CachedSpeech(cached, True, _ms(start))
        outcome = await timed_call(lambda: self._tts.synthesize(text), self._timeout_s)
        if not outcome.ok or outcome.value is None:
            return CachedSpeech(
                None, False, outcome.elapsed_ms, outcome.error or "no audio", outcome.timed_out
            )
        self._store(text, outcome.value)
        return CachedSpeech(outcome.value, False, outcome.elapsed_ms)

    def _store(self, text: str, audio: SpeechAudio) -> None:
        target = self.path_for(text)
        tmp = target.with_suffix(".wav.tmp")
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(pcm16_to_wav(audio.pcm16, audio.sample_rate))
            os.replace(tmp, target)
        except OSError as exc:  # no cache is slower, not broken
            self._on_error("tts_error", {"error": describe_error(exc), "cache": "write_failed"})

    async def prewarm(
        self, texts: Iterable[str], *, timeout_s: float, concurrency: int
    ) -> PrewarmReport:
        start = time.perf_counter()
        unique = list(dict.fromkeys(texts))
        missing = [text for text in unique if not self.path_for(text).is_file()]
        semaphore = asyncio.Semaphore(concurrency)
        results: list[bool] = []

        async def warm(text: str) -> None:
            async with semaphore:
                results.append((await self.get(text)).audio is not None)

        tasks = [asyncio.ensure_future(warm(text)) for text in missing]
        timed_out = False
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=timeout_s)
            timed_out = bool(pending)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        synthesized = sum(results)
        return PrewarmReport(
            lines=len(unique),
            already_cached=len(unique) - len(missing),
            synthesized=synthesized,
            failed=len(missing) - synthesized,
            timed_out=timed_out,
            elapsed_ms=_ms(start),
        )


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
