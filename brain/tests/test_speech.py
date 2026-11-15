"""Audio gate, segmenter, audio utils, VAD, model cache, AudioInput, STT/TTS adapters."""

from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from pipi_brain.config import VadConfig, load_config
from pipi_brain.fakes import FakeMicrophone, FakeVad, make_frames
from pipi_brain.speech import model_cache
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.audio_input import AudioInput
from pipi_brain.speech.audio_utils import (
    SILENCE_DBFS,
    float_to_pcm16,
    pcm16_to_float,
    rms_dbfs,
    samples_to_wav,
)
from pipi_brain.speech.base import MicrophoneError, SpeechAudio
from pipi_brain.speech.model_cache import ModelDownloadError, ensure_model
from pipi_brain.speech.segmenter import UtteranceSegmenter
from pipi_brain.speech.stt import OpenAISpeechToText
from pipi_brain.speech.tts import TTS_PCM_SAMPLE_RATE, OpenAITextToSpeech
from pipi_brain.speech.vad import EnergyVad, SileroVad, create_vad

from .conftest import CONFIG_DIR

FRAME_S = 512 / 16000  # 32 ms


@pytest.fixture
def vad_config() -> VadConfig:
    return load_config(CONFIG_DIR / "dev.yaml").app.vad


def _segmenter(config: VadConfig, **overrides: Any) -> UtteranceSegmenter:
    return UtteranceSegmenter(
        config.model_copy(update=overrides), sample_rate=16000, frame_samples=512
    )


# --- audio gate -----------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


def test_gate_rejects_frames_while_speaking_and_during_tail() -> None:
    clock = _Clock()
    gate = AudioGate(tail_ms=300, clock=clock)
    assert gate.is_open and gate.accepts(9.9)
    with gate.speaking():
        assert not gate.is_open
        assert not gate.accepts(10.0)
        clock.now = 12.0
        assert not gate.accepts(11.5)
    assert not gate.accepts(11.9)  # captured while Pipi was speaking
    assert not gate.accepts(12.2)  # inside the 300 ms tail
    assert gate.accepts(12.3)
    clock.now = 12.31
    assert gate.is_open


def test_gate_opens_again_after_an_exception() -> None:
    gate = AudioGate(tail_ms=0)
    with pytest.raises(RuntimeError), gate.speaking():
        raise RuntimeError("playback crashed")
    assert gate.is_open


# --- segmenter ------------------------------------------------------------------------------


def _push_all(segmenter: UtteranceSegmenter, frames: list[Any]) -> list[Any]:
    vad = FakeVad()
    results = [segmenter.push(f, vad.speech_probability(f.samples)) for f in frames]
    return [r for r in results if r is not None]


def test_speech_followed_by_silence_gives_one_utterance(vad_config: VadConfig) -> None:
    frames = make_frames([(0, 20), (0.5, 30), (0, 40)])
    utterances = _push_all(_segmenter(vad_config), frames)
    assert len(utterances) == 1
    utt = utterances[0]
    assert not utt.truncated
    assert utt.started_at == pytest.approx(frames[20].captured_at)
    # pre-roll (300 ms -> 10 frames) + 30 speech frames + 22 silence frames (>= 700 ms)
    assert len(utt.samples) == (10 + 30 + 22) * 512


def test_short_blip_is_dropped(vad_config: VadConfig) -> None:
    frames = make_frames([(0, 5), (0.5, 3), (0, 40)])  # 96 ms < min_speech_ms 250
    assert _push_all(_segmenter(vad_config), frames) == []


def test_short_pause_inside_speech_does_not_end_the_utterance(vad_config: VadConfig) -> None:
    frames = make_frames([(0.5, 20), (0, 10), (0.5, 20), (0, 40)])  # 320 ms pause < 700 ms
    utterances = _push_all(_segmenter(vad_config, pre_roll_ms=0), frames)
    assert len(utterances) == 1
    assert len(utterances[0].samples) == (20 + 10 + 20 + 22) * 512


def test_long_speech_is_truncated_at_max_length(vad_config: VadConfig) -> None:
    frames = make_frames([(0.5, 100)])  # 3.2 s of speech, max 1 s
    utterances = _push_all(_segmenter(vad_config, max_utterance_s=1.0, pre_roll_ms=0), frames)
    assert utterances and utterances[0].truncated
    assert utterances[0].duration_ms == pytest.approx(1000, abs=40)


def test_hysteresis_band_counts_as_speech(vad_config: VadConfig) -> None:
    segmenter = _segmenter(vad_config, pre_roll_ms=0)
    frames = make_frames([(0.5, 40)])
    segmenter.push(frames[0], 0.9)
    for frame in frames[1:]:
        assert segmenter.push(frame, 0.4) is None  # between 0.35 and 0.5: still talking
    assert segmenter.in_speech


# --- audio utils + VAD ----------------------------------------------------------------------


def test_pcm_roundtrip_and_wav_header() -> None:
    samples = np.array([0.0, 0.5, -0.5, 1.5], dtype=np.float32)
    back = pcm16_to_float(float_to_pcm16(samples))
    assert back == pytest.approx([0.0, 0.5, -0.5, 1.0], abs=1e-3)  # 1.5 is clipped
    with wave.open(io.BytesIO(samples_to_wav(samples, 16000))) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (16000, 1, 4)


def test_rms_dbfs() -> None:
    assert rms_dbfs(np.zeros(512, dtype=np.float32)) == SILENCE_DBFS
    assert rms_dbfs(np.ones(512, dtype=np.float32)) == pytest.approx(0.0)
    assert rms_dbfs(np.zeros(0, dtype=np.float32)) == SILENCE_DBFS


def test_energy_vad() -> None:
    vad = EnergyVad(threshold_dbfs=-40)
    quiet, loud = make_frames([(0.001, 1), (0.5, 1)])
    assert vad.speech_probability(quiet.samples) == 0.0
    assert vad.speech_probability(loud.samples) == 1.0


def test_energy_engine_needs_no_model(vad_config: VadConfig) -> None:
    choice = create_vad(
        vad_config.model_copy(update={"engine": "energy"}), sample_rate=16000, frame_samples=512
    )
    assert choice.vad.name == "energy" and choice.fallback_reason is None


def test_silero_falls_back_to_energy_when_model_is_unavailable(
    vad_config: VadConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args: Any, **kwargs: Any) -> None:
        raise OSError("network unreachable")

    monkeypatch.setattr(model_cache, "_download", no_network)
    config = vad_config.model_copy(update={"model_path": tmp_path / "missing.onnx"})
    choice = create_vad(config, sample_rate=16000, frame_samples=512)
    assert choice.vad.name == "energy"
    assert choice.fallback_reason is not None and "network unreachable" in choice.fallback_reason


@pytest.mark.skipif(
    not (CONFIG_DIR.parent / "cache" / "silero_vad.onnx").is_file(),
    reason="Silero model not downloaded yet (it is fetched on the first voice-loop run)",
)
def test_real_silero_model_gives_low_probability_for_silence(vad_config: VadConfig) -> None:
    vad = SileroVad(vad_config.model_path, sample_rate=16000, frame_samples=512)
    probabilities = [vad.speech_probability(np.zeros(512, dtype=np.float32)) for _ in range(10)]
    assert max(probabilities) < vad_config.threshold
    with pytest.raises(ValueError, match="512"):
        vad.speech_probability(np.zeros(100, dtype=np.float32))


# --- model cache ----------------------------------------------------------------------------


def _fake_download(content: bytes) -> Any:
    def download(url: str, target: Path, timeout_s: float) -> None:
        target.write_bytes(content)

    return download


def test_model_is_downloaded_verified_and_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"fake onnx model"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(model_cache, "_download", _fake_download(content))
    target = tmp_path / "cache" / "model.onnx"
    assert ensure_model(target, url="https://x/model.onnx", sha256=digest, timeout_s=1) == target
    assert target.read_bytes() == content

    monkeypatch.setattr(model_cache, "_download", None)  # a second call must not download
    assert ensure_model(target, url="https://x/model.onnx", sha256=digest, timeout_s=1) == target


def test_checksum_mismatch_is_rejected_and_cleaned_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_cache, "_download", _fake_download(b"tampered"))
    target = tmp_path / "model.onnx"
    with pytest.raises(ModelDownloadError, match="checksum"):
        ensure_model(target, url="https://x/m.onnx", sha256="0" * 64, timeout_s=1)
    assert list(tmp_path.iterdir()) == []


def test_non_https_url_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ModelDownloadError, match="non-https"):
        ensure_model(tmp_path / "m.onnx", url="http://x/m.onnx", sha256="0" * 64, timeout_s=1)


# --- AudioInput -----------------------------------------------------------------------------


def _audio_input(frames: list[Any], vad_config: VadConfig, gate: AudioGate | None = None) -> Any:
    return AudioInput(
        microphone=FakeMicrophone(frames),
        vad=FakeVad(),
        segmenter=_segmenter(vad_config),
        gate=gate or AudioGate(tail_ms=0),
        frame_timeout_s=1.0,
    )


async def test_listen_returns_an_utterance_and_reports_speech_start(
    vad_config: VadConfig,
) -> None:
    started: list[bool] = []
    audio_input = _audio_input(make_frames([(0, 10), (0.5, 30), (0, 30)]), vad_config)
    utterance = await audio_input.listen(5.0, on_speech_start=lambda: started.append(True))
    assert utterance is not None and utterance.duration_ms > 900
    assert started == [True]


async def test_listen_returns_none_after_silence_timeout(vad_config: VadConfig) -> None:
    frames = make_frames([(0, 200)])  # 6.4 s of silence
    assert await _audio_input(frames, vad_config).listen(2.0) is None


async def test_listen_ignores_frames_captured_while_pipi_speaks(vad_config: VadConfig) -> None:
    frames = make_frames([(0.5, 30), (0, 30), (0.5, 30), (0, 30)])
    gate = AudioGate(tail_ms=0, clock=lambda: frames[60].captured_at)
    gate.close()
    gate.open()  # the mic "opens" at frame 60: the first burst was Pipi's own voice
    utterance = await _audio_input(frames, vad_config, gate).listen(10.0)
    assert utterance is not None
    assert utterance.started_at == pytest.approx(frames[60].captured_at)


async def test_listen_raises_when_the_microphone_dies(vad_config: VadConfig) -> None:
    with pytest.raises(MicrophoneError):
        await _audio_input(make_frames([(0.5, 5)]), vad_config).listen(5.0)


# --- STT / TTS adapters (fake OpenAI client) ------------------------------------------------


async def test_stt_adapter_sends_wav_and_strips_text() -> None:
    sent: dict[str, Any] = {}

    async def create(**kwargs: Any) -> Any:
        sent.update(kwargs)
        return SimpleNamespace(text="  hello Pipi \n")

    client: Any = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
    )
    stt = OpenAISpeechToText(client, model="gpt-4o-mini-transcribe")
    assert await stt.transcribe(b"RIFF...") == "hello Pipi"
    assert sent["model"] == "gpt-4o-mini-transcribe"
    assert sent["language"] == "en"
    assert sent["file"] == ("utterance.wav", b"RIFF...", "audio/wav")


async def test_tts_adapter_requests_raw_pcm() -> None:
    sent: dict[str, Any] = {}

    async def create(**kwargs: Any) -> Any:
        sent.update(kwargs)
        return SimpleNamespace(content=b"\x00\x00" * 2400)

    client: Any = SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=create)))
    tts = OpenAITextToSpeech(client, model="tts-1", voice="nova")
    audio = await tts.synthesize("Hi!")
    assert audio == SpeechAudio(pcm16=b"\x00\x00" * 2400, sample_rate=TTS_PCM_SAMPLE_RATE)
    assert audio.duration_s == pytest.approx(0.1)
    assert (sent["model"], sent["voice"], sent["response_format"]) == ("tts-1", "nova", "pcm")
