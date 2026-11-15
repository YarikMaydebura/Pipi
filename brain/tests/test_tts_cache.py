"""The TTS disk cache for fixed lines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipi_brain.fakes import FakeTextToSpeech
from pipi_brain.speech.tts_cache import TtsCache, cache_key


def cache(folder: Path, tts: FakeTextToSpeech, voice: str = "nova") -> tuple[TtsCache, list[Any]]:
    errors: list[Any] = []
    return (
        TtsCache(
            folder,
            tts=tts,
            model="tts-1",
            voice=voice,
            timeout_s=1,
            on_error=lambda kind, data: errors.append((kind, data)),
        ),
        errors,
    )


def files(folder: Path) -> list[Path]:
    return list(folder.iterdir())


async def test_miss_synthesizes_and_stores_then_hit_is_free(tmp_path: Path) -> None:
    tts = FakeTextToSpeech()
    c, _ = cache(tmp_path / "tts", tts)
    first = await c.get("Break time!")
    assert first.audio is not None and not first.from_cache
    second = await c.get("Break time!")
    assert second.from_cache and second.audio == first.audio
    assert tts.texts == ["Break time!"]
    (stored,) = files(tmp_path / "tts")
    assert "Break" not in stored.name and stored.suffix == ".wav"


def test_key_depends_on_voice_model_and_text() -> None:
    base = cache_key("Hi", voice="nova", model="tts-1")
    assert base != cache_key("Hi", voice="alloy", model="tts-1")
    assert base != cache_key("Hi!", voice="nova", model="tts-1")
    assert base == cache_key("Hi", voice="nova", model="tts-1")


async def test_failure_returns_no_audio_and_stores_nothing(tmp_path: Path) -> None:
    tts = FakeTextToSpeech(failures=[RuntimeError("down")])
    c, _ = cache(tmp_path, tts)
    result = await c.get("Hi")
    assert result.audio is None and "down" in (result.error or "")
    assert files(tmp_path) == []


async def test_unreadable_file_is_reported_and_resynthesized(tmp_path: Path) -> None:
    tts = FakeTextToSpeech()
    c, errors = cache(tmp_path, tts)
    c.path_for("Hi").write_bytes(b"not a wav")
    result = await c.get("Hi")
    assert result.audio is not None and not result.from_cache
    assert errors[0][1]["cache"] == "unreadable"


async def test_prewarm_counts_lines(tmp_path: Path) -> None:
    tts = FakeTextToSpeech()
    c, _ = cache(tmp_path, tts)
    await c.get("already")
    tts.failures = [RuntimeError("one fails")]
    report = await c.prewarm(["already", "a", "b", "a"], timeout_s=5, concurrency=2)
    assert report.lines == 3 and report.already_cached == 1
    assert report.synthesized + report.failed == 2 and report.failed == 1
    assert not report.timed_out


async def test_session_prewarms_and_plays_fixed_lines_from_the_cache(
    dev_config: Any, dialogue_content: Any, tmp_path: Path
) -> None:
    from .session_harness import make_session, turn

    folder = tmp_path / "cache"
    s = make_session(
        dev_config,
        dialogue_content,
        tmp_path,
        script=["calm", "I'm Lena"],
        llm=[turn("Hi Lena!", memory_updates={"name": "Lena"})],
        tts_cache_dir=folder,
    )
    await s.run()
    report = s.data("tts_prewarm")[0]
    assert report["lines"] > 20 and report["failed"] == 0
    spoken = [d for d in s.data("turn") if d["speaker"] == "pipi"]
    assert "Ta-da! Hi again, Lena!" in [d["text"] for d in spoken]
    assert any(d["tts_cached"] for d in spoken if d.get("line_id"))
    # no participant data on disk: lines with the name are never cached
    assert s.ctl.voice._cache is not None  # type: ignore[attr-defined]
    assert not s.ctl.voice._cache.path_for("Ta-da! Hi again, Lena!").exists()  # type: ignore[attr-defined]
