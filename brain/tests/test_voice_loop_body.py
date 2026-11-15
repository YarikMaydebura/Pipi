"""The voice loop speaking through a body (``--body pet``), with a fake body."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.fakes import FakeBody, FakeTextToSpeech

from .test_voice_loop import Harness, make_harness, turn_json


def with_body(h: Harness, body: FakeBody) -> Harness:
    h.loop._deps = dataclasses.replace(h.loop._deps, body=body)  # noqa: SLF001
    return h


async def test_speech_goes_to_the_body_with_listening_and_thinking_eyes(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    body = FakeBody()
    h = with_body(
        make_harness(dev_config, dialogue_content, tmp_path, typed=["hi"], chat=[turn_json("Yo!")]),
        body,
    )
    await h.loop.run(max_user_turns=1)
    assert h.speaker.played == []  # nothing on the laptop speaker
    assert [text for text, _, _ in body.spoken] == [
        dialogue_content.line("opening", "cheerful"),
        "Yo!",
    ]
    assert body.spoken[1][2] == "happy"
    names = [name for name, _ in body.calls]
    assert names == ["speak", "eyes", "eyes", "motion", "speak"]
    assert [arg for name, arg in body.calls if name == "eyes"] == ["listening", "thinking"]
    assert ("motion", "nod") in body.calls
    assert "Pipi: Yo!" in h.output  # the terminal still shows the text


async def test_mic_is_gated_while_the_body_speaks(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    gate_states: list[bool] = []
    body = FakeBody()
    h = with_body(make_harness(dev_config, dialogue_content, tmp_path, typed=[]), body)
    body.on_speak = lambda: gate_states.append(h.gate.is_open)
    await h.loop.run()
    assert gate_states == [False]
    assert h.gate.is_open


async def test_missing_body_falls_back_to_the_laptop_speaker(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    body = FakeBody(connected=False)
    h = with_body(make_harness(dev_config, dialogue_content, tmp_path, typed=[]), body)
    await h.loop.run()
    assert len(h.speaker.played) == 1
    fallback = h.events("body_fallback")[0]["data"]
    assert fallback == {
        "body": "desktop_pet",
        "action": "speak",
        "error": "not connected",
        "fallback": "local_speaker",
    }
    assert not [name for name, _ in body.calls if name == "eyes"]  # not sent while away


async def test_captions_only_on_the_body_when_tts_fails(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    body = FakeBody()
    tts = FakeTextToSpeech(failures=[RuntimeError("tts down")])
    h = with_body(make_harness(dev_config, dialogue_content, tmp_path, typed=[], tts=tts), body)
    await h.loop.run()
    assert body.spoken[0][1] is None
    assert h.gate.is_open  # no audio -> the mic was never closed
    assert h.speaker.played == []


async def test_events_carry_the_body_name(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    h = with_body(make_harness(dev_config, dialogue_content, tmp_path, typed=[]), FakeBody())
    h.loop._settings = dataclasses.replace(h.loop._settings, log_body="desktop_pet")  # noqa: SLF001
    await h.loop.run()
    assert {e["body"] for e in h.events()} == {"desktop_pet"}
