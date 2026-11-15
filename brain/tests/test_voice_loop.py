"""The turn loop end to end, with fakes for every external dependency."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.fakes import (
    FakeChatModel,
    FakeMicrophone,
    FakeSpeaker,
    FakeSpeechToText,
    FakeTextInput,
    FakeTextToSpeech,
    FakeVad,
    make_frames,
)
from pipi_brain.logging_study import StudyLogger
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.audio_input import AudioInput
from pipi_brain.speech.base import SpeakerError
from pipi_brain.speech.segmenter import UtteranceSegmenter
from pipi_brain.voice_loop import VoiceLoop, VoiceLoopDeps, VoiceLoopSettings

SPEECH = [(0, 5), (0.5, 30), (0, 30)]  # ~1 s of "speech" then enough silence to end it


def turn_json(say: str, **updates: Any) -> str:
    return json.dumps(
        {"say": say, "expression": "happy", "gesture": "nod", "memory_updates": updates}
    )


@dataclass
class Harness:
    loop: VoiceLoop
    logger: StudyLogger
    gate: AudioGate
    stt: FakeSpeechToText
    tts: FakeTextToSpeech
    speaker: FakeSpeaker
    chat: FakeChatModel
    output: list[str] = field(default_factory=list)

    def events(self, event_type: str | None = None) -> list[dict[str, Any]]:
        events = self.logger.read_events()
        return [e for e in events if event_type is None or e["type"] == event_type]

    def pipi_turns(self) -> list[dict[str, Any]]:
        return [e["data"] for e in self.events("turn") if e["data"]["speaker"] == "pipi"]


def make_harness(
    config: LoadedConfig,
    content: DialogueContent,
    tmp_path: Path,
    *,
    chat: list[object] | None = None,
    stt: list[object] | None = None,
    typed: list[str | None] | None = None,
    mic_segments: list[tuple[float, int]] | None = None,
    tts: FakeTextToSpeech | None = None,
    speaker: FakeSpeaker | None = None,
    llm_timeout_s: float = 1.0,
    stt_timeout_s: float = 1.0,
    playback_margin_s: float = 1.0,
) -> Harness:
    app = config.app
    # Fake frames are stamped from t=100 s; a fixed clock keeps the gate on that timeline.
    gate = AudioGate(tail_ms=0, clock=lambda: 0.0)
    audio_input = None
    if mic_segments is not None:
        audio_input = AudioInput(
            microphone=FakeMicrophone(make_frames(mic_segments)),
            vad=FakeVad(),
            segmenter=UtteranceSegmenter(app.vad, sample_rate=16000, frame_samples=512),
            gate=gate,
            frame_timeout_s=1.0,
        )
    fakes = {
        "stt": FakeSpeechToText(list(stt or [])),
        "tts": tts or FakeTextToSpeech(),
        "speaker": speaker or FakeSpeaker(),
        "chat": FakeChatModel(list(chat or [])),
    }
    deps = VoiceLoopDeps(
        stt=fakes["stt"],
        tts=fakes["tts"],
        speaker=fakes["speaker"],
        dialogue=DialogueEngine(fakes["chat"], timeout_s=llm_timeout_s, retries=1),
        text_input=FakeTextInput(list(typed or [])),
        audio_input=audio_input,
    )
    settings = VoiceLoopSettings(
        participant_id="P01",
        persona_id="cheerful",
        history_turns=6,
        silence_reprompt_s=2.0,
        stt_timeout_s=stt_timeout_s,
        tts_timeout_s=1.0,
        playback_margin_s=playback_margin_s,
    )
    logger = StudyLogger(tmp_path / "logs", "P01")
    output: list[str] = []
    loop = VoiceLoop(
        deps=deps,
        settings=settings,
        content=content,
        logger=logger,
        gate=gate,
        emit=output.append,
    )
    return Harness(loop, logger, gate, output=output, **fakes)  # type: ignore[arg-type]


async def test_voice_turn_happy_path_logs_latencies_and_remembers_the_name(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config,
        dialogue_content,
        tmp_path,
        mic_segments=SPEECH,
        stt=["I'm Lena"],
        chat=[turn_json("Nice to meet you, Lena!", name="Lena")],
    )
    await h.loop.run(max_user_turns=1)

    assert h.loop.memory.name == "Lena"
    assert h.tts.texts == [dialogue_content.line("opening", "cheerful"), "Nice to meet you, Lena!"]
    assert len(h.speaker.played) == 2
    user_turn = next(e["data"] for e in h.events("turn") if e["data"]["speaker"] == "user")
    assert user_turn["text"] == "I'm Lena" and user_turn["input"] == "voice"
    assert user_turn["audio_ms"] > 0
    reply = h.pipi_turns()[1]
    for key in ("stt_ms", "llm_ms", "tts_ms", "total_ms"):
        assert isinstance(reply[key], int)
    assert reply["fallback_used"] is None and reply["llm_attempts"] == 1
    assert (reply["expression"], reply["gesture"]) == ("happy", "nod")
    assert any(line.startswith("  [latency] stt ") for line in h.output)
    assert "You: I'm Lena" in h.output
    # The name is only in memory.json, never in the memory_update event.
    assert h.events("memory_update")[0]["data"] == {"fields": ["name"]}
    memory = json.loads((h.logger.folder / "memory.json").read_text(encoding="utf-8"))
    assert memory["name"] == "Lena"


async def test_memory_reaches_the_next_prompt(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config,
        dialogue_content,
        tmp_path,
        typed=["I'm Lena", "what's my name?"],
        chat=[turn_json("Hi Lena!", name="Lena"), turn_json("You're Lena, of course!")],
    )
    await h.loop.run(max_user_turns=2)
    second_prompt = h.chat.calls[1]
    assert "Participant's name: Lena" in second_prompt[1]["content"]
    assert "Participant: I'm Lena" in second_prompt[1]["content"]  # history
    assert second_prompt[2] == {"role": "user", "content": "what's my name?"}


async def test_typed_turn_has_no_stt_latency(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config, dialogue_content, tmp_path, typed=["hello", "/quit"], chat=[turn_json("Hi!")]
    )
    await h.loop.run()
    reply = h.pipi_turns()[1]
    assert reply["stt_ms"] is None and isinstance(reply["total_ms"], int)
    assert h.loop.user_turns == 1
    assert h.stt.calls == []


async def test_invalid_llm_output_twice_uses_fallback_line_and_logs_errors(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config, dialogue_content, tmp_path, typed=["hi"], chat=["{oops", "still not json"]
    )
    await h.loop.run(max_user_turns=1)
    fallback = dialogue_content.line("llm_fallback", "cheerful")
    assert h.pipi_turns()[1]["text"] == fallback
    assert h.pipi_turns()[1]["fallback_used"] == "llm_fallback"
    errors = [e["data"] for e in h.events("llm_error")]
    assert [(e["attempt"], e["retry"], e["fallback"]) for e in errors] == [
        (1, True, False),
        (2, False, True),
    ]


async def test_llm_timeout_falls_back(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config, dialogue_content, tmp_path, typed=["hi"], chat=[], llm_timeout_s=0.02
    )
    h.chat.delay_s = 0.5
    h.chat.answers.extend([turn_json("late"), turn_json("late")])
    await h.loop.run(max_user_turns=1)
    assert h.pipi_turns()[1]["fallback_used"] == "llm_fallback"
    assert all("timeout" in e["data"]["error"] for e in h.events("llm_error"))


async def test_stt_error_asks_to_repeat_without_calling_the_llm(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config,
        dialogue_content,
        tmp_path,
        mic_segments=SPEECH + [(0, 200)],
        stt=[ConnectionError("network down")],
    )
    await h.loop.run(max_user_turns=1)
    assert h.chat.calls == []
    assert h.events("stt_error")[0]["data"]["fallback"] == "stt_retry"
    retry_turn = h.pipi_turns()[1]
    assert retry_turn["text"] == dialogue_content.line("stt_retry", "cheerful")
    assert retry_turn["fallback_used"] == "stt_error"
    assert isinstance(retry_turn["stt_ms"], int)


async def test_empty_transcript_is_a_clarification(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config, dialogue_content, tmp_path, mic_segments=SPEECH + [(0, 200)], stt=["  "]
    )
    await h.loop.run(max_user_turns=1)
    assert h.events("clarification")[0]["data"] == {"reason": "empty_transcript"}
    assert h.chat.calls == []


async def test_tts_failure_gives_captions_only(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    tts = FakeTextToSpeech(failures=[RuntimeError("tts down")])
    h = make_harness(
        dev_config, dialogue_content, tmp_path, typed=["hi"], chat=[turn_json("Hi!")], tts=tts
    )
    await h.loop.run(max_user_turns=1)
    assert h.events("tts_error")[0]["data"]["fallback"] == "captions_only"
    assert h.pipi_turns()[0]["audio"] is False
    assert len(h.speaker.played) == 1  # only the reply; the opening line had no audio
    assert f"Pipi: {dialogue_content.line('opening', 'cheerful')}" in h.output


async def test_speaker_failure_is_logged_and_the_session_continues(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    speaker = FakeSpeaker(fail_with=SpeakerError("no output device"))
    h = make_harness(
        dev_config,
        dialogue_content,
        tmp_path,
        typed=["hi"],
        chat=[turn_json("Hi!")],
        speaker=speaker,
    )
    await h.loop.run(max_user_turns=1)
    errors = h.events("audio_error")
    assert len(errors) == 2 and errors[0]["data"]["device"] == "speaker"
    assert h.loop.user_turns == 1


async def test_playback_timeout_stops_the_speaker(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    speaker = FakeSpeaker(delay_s=5.0)
    h = make_harness(
        dev_config, dialogue_content, tmp_path, typed=[], speaker=speaker, playback_margin_s=0.01
    )
    await h.loop.run()
    assert speaker.stops == 1
    assert "timeout" in h.events("audio_error")[0]["data"]["error"]


async def test_mic_is_gated_while_pipi_speaks(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    gate_states: list[bool] = []
    speaker = FakeSpeaker()
    h = make_harness(dev_config, dialogue_content, tmp_path, typed=[], speaker=speaker)
    speaker.on_play = lambda: gate_states.append(h.gate.is_open)
    await h.loop.run()
    assert gate_states == [False]
    assert h.gate.is_open  # tail_ms=0: open again right after playback


async def test_silence_gives_one_reprompt(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    # 2 s silence timeout: ~6.4 s of silence = two silent periods, then speech.
    h = make_harness(
        dev_config,
        dialogue_content,
        tmp_path,
        mic_segments=[(0, 200), *SPEECH],
        stt=["hello"],
        chat=[turn_json("Hi!")],
    )
    await h.loop.run(max_user_turns=1)
    assert len(h.events("silence_reprompt")) == 1
    texts = [t["text"] for t in h.pipi_turns()]
    assert texts.count(dialogue_content.line("silence_reprompt", "cheerful")) == 1


async def test_microphone_failure_switches_to_typed_input(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config,
        dialogue_content,
        tmp_path,
        mic_segments=[(0, 3)],  # the fake mic dies after 3 frames
        typed=["typed hello"],
        chat=[turn_json("Hi!")],
    )
    await h.loop.run(max_user_turns=1)
    error = h.events("audio_error")[0]["data"]
    assert (error["device"], error["fallback"]) == ("microphone", "typed_input")
    assert h.loop.input_mode == "typed"
    assert h.loop.user_turns == 1


async def test_greeting_moves_to_chat_once_everything_is_known(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(
        dev_config,
        dialogue_content,
        tmp_path,
        typed=["Lena", "chess", "tired"],
        chat=[
            turn_json("Hi Lena!", name="Lena"),
            turn_json("Chess, nice!", interests=["chess"]),
            turn_json("I'll be right here.", reading_feeling="tired"),
        ],
    )
    await h.loop.run(max_user_turns=3)
    assert h.loop.phase == "CHAT"
    change = h.events("phase_change")[0]["data"]
    assert change == {"from": "GREETING", "to": "CHAT", "trigger": "auto"}
    assert "Current phase: GREETING" in h.chat.calls[2][0]["content"]


async def test_finalize_writes_summary_memory_and_session_end(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = make_harness(dev_config, dialogue_content, tmp_path, typed=["hi"], chat=[turn_json("Hi!")])
    await h.loop.run(max_user_turns=1)
    summary = h.loop.finalize("completed")
    assert summary["user_turns"] == 1
    assert summary["latency"]["total_ms"]["count"] == 1
    assert h.events("session_end")[0]["data"]["reason"] == "completed"
    saved = json.loads((h.logger.folder / "summary.json").read_text(encoding="utf-8"))
    assert saved["event_counts"]["turn"] == 3
    assert (h.logger.folder / "memory.json").is_file()


@pytest.mark.parametrize("command", ["/quit", "exit", None])
async def test_quit_commands_end_the_loop(
    dev_config: LoadedConfig,
    dialogue_content: DialogueContent,
    tmp_path: Path,
    command: str | None,
) -> None:
    h = make_harness(dev_config, dialogue_content, tmp_path, typed=["", command])
    await h.loop.run()
    assert h.loop.user_turns == 0
