"""DesktopPetBody + BodyChannel: acks, speech_done, timeouts, disconnects and logging.

A fake link answers like the pet would; no sockets are involved here (see test_server.py).
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping
from typing import Any

import pytest

from pipi_brain.bodies.desktop_pet import DesktopPetBody, caption_seconds, encode_audio_wav_b64
from pipi_brain.config import BodiesConfig
from pipi_brain.protocol import Ack, Hello, SpeechDone
from pipi_brain.speech.base import SpeechAudio

SETTINGS = BodiesConfig(
    hello_timeout_s=1,
    ack_timeout_s=0.1,
    ack_retries=1,
    migration_timeout_s=0.3,
    speech_done_margin_s=0.1,
    caption_s_per_char=0.001,
    connect_wait_s=0.05,
)
HELLO = Hello(body="desktop_pet", version="0.1.0")
AUDIO = SpeechAudio(pcm16=b"\x01\x00" * 2400, sample_rate=24000)  # 0.1 s


class EventLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_type: str, data: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(data)))

    def of(self, event_type: str) -> list[dict[str, Any]]:
        return [data for kind, data in self.events if kind == event_type]


class FakePetLink:
    """Answers each message like the pet: ack (configurable) and speech_done for speak."""

    def __init__(
        self,
        pet: DesktopPetBody,
        *,
        ack: bool = True,
        ack_ok: bool = True,
        speech_done: bool = True,
    ) -> None:
        self.description = "fake-pet"
        self.pet = pet
        self.ack = ack
        self.ack_ok = ack_ok
        self.speech_done = speech_done
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        asyncio.get_running_loop().call_soon(self._answer, message)

    def _answer(self, message: dict[str, Any]) -> None:
        if self.ack:
            error = None if self.ack_ok else "unknown motion"
            self.pet.receive(Ack(ref_id=message["id"], ok=self.ack_ok, error=error))
        if self.speech_done and message["type"] == "speak":
            self.pet.receive(SpeechDone(ref_id=message["id"], duration_ms=123))

    async def close(self) -> None:
        self.closed = True

    def types(self) -> list[str]:
        return [m["type"] for m in self.sent]


def make_pet(**link_options: Any) -> tuple[DesktopPetBody, FakePetLink, EventLog]:
    log = EventLog()
    pet = DesktopPetBody(SETTINGS, robot_side="left", log=log)
    return pet, FakePetLink(pet, **link_options), log


async def connected_pet(**link_options: Any) -> tuple[DesktopPetBody, FakePetLink, EventLog]:
    pet, link, log = make_pet(**link_options)
    pet.attach(link, HELLO)
    await asyncio.sleep(0.01)  # let body_config go out and be acked
    return pet, link, log


async def test_connecting_sends_the_robot_side_first() -> None:
    pet, link, log = await connected_pet()
    assert pet.connected and pet.health() == "connected (pet 0.1.0)"
    assert link.sent[0]["type"] == "body_config" and link.sent[0]["robot_side"] == "left"
    assert log.of("body_connected") == [{"remote": "fake-pet", "version": "0.1.0"}]


async def test_eyes_are_acked_and_every_message_is_logged() -> None:
    pet, link, log = await connected_pet()
    result = await pet.set_eyes("happy")
    assert result.ok and not result.timed_out
    outgoing = [e for e in log.of("body_message") if e["direction"] == "out"]
    incoming = [e for e in log.of("body_message") if e["direction"] == "in"]
    assert [e["type"] for e in outgoing] == ["body_config", "eyes"]
    assert outgoing[1]["state"] == "happy"
    assert [e["ref_id"] for e in incoming] == [m["id"] for m in link.sent]


async def test_missing_pet_is_a_logged_failure_not_a_crash() -> None:
    pet, _, log = make_pet()
    result = await pet.play_motion("wave")
    assert not result.ok and result.error == "not connected"
    assert log.of("body_error")[0]["message_type"] == "motion"
    speak = await pet.speak("hi", AUDIO)
    assert not speak.delivered and speak.error == "not connected"
    assert await pet.wait_connected(0.01) is False


async def test_harmless_commands_are_retried_once_after_a_timeout() -> None:
    pet, link, log = await connected_pet()
    link.ack = False
    result = await pet.set_eyes("thinking")
    assert not result.ok and result.timed_out
    assert link.types().count("eyes") == 2
    errors = log.of("body_error")
    assert [e["retry"] for e in errors] == [True, False]


async def test_motions_are_not_retried() -> None:
    pet, link, _ = await connected_pet()
    link.ack = False
    assert not (await pet.play_motion("wave")).ok
    assert link.types().count("motion") == 1


async def test_refusal_carries_the_pets_reason() -> None:
    pet, link, _ = await connected_pet()
    link.ack_ok = False
    result = await pet.play_motion("moonwalk")
    assert result.error == "body refused: unknown motion"


async def test_speak_sends_a_wav_and_waits_for_speech_done() -> None:
    pet, link, log = await connected_pet()
    result = await pet.speak("Hello!", AUDIO, "happy")
    assert result.delivered and result.finished and result.duration_ms == 123
    speak = link.sent[-1]
    assert speak["expression"] == "happy" and speak["text"] == "Hello!"
    wav = base64.b64decode(speak["audio_b64"])
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    logged = [e for e in log.of("body_message") if e.get("type") == "speak"][0]
    assert logged["has_audio"] is True and "audio_b64" not in logged


async def test_captions_only_speak_has_no_audio() -> None:
    pet, link, _ = await connected_pet()
    result = await pet.speak("Just text", None)
    assert result.finished
    assert link.sent[-1].get("audio_b64") is None


async def test_missing_speech_done_is_logged_but_counts_as_delivered() -> None:
    pet, _, log = await connected_pet(speech_done=False)
    result = await pet.speak("Hi", AUDIO)
    assert result.delivered and not result.finished
    assert "speech_done" in (result.error or "")
    assert log.of("body_error")[-1]["message_type"] == "speak"


async def test_disconnect_while_waiting_fails_fast() -> None:
    pet, link, log = await connected_pet(ack=False)
    task = asyncio.create_task(pet.activate("jump_in"))
    await asyncio.sleep(0.01)
    pet.detach(link, "connection lost")
    result = await task
    assert not result.ok and "disconnected" in (result.error or "")
    assert not pet.connected
    assert log.of("body_disconnected")[0]["reason"] == "connection lost"


async def test_a_new_connection_replaces_the_old_one() -> None:
    pet, first, _ = await connected_pet()
    second = FakePetLink(pet)
    assert pet.attach(second, HELLO) is first
    pet.detach(first, "late close of the old socket")  # ignored: not the current link
    assert pet.connected
    await asyncio.sleep(0.01)
    assert (await pet.set_eyes("idle")).ok
    assert second.types()[-1] == "eyes"


def test_wav_encoding_and_caption_estimate() -> None:
    wav = base64.b64decode(encode_audio_wav_b64(AUDIO))
    assert len(wav) == 44 + len(AUDIO.pcm16)
    assert caption_seconds("short", 0.07) == pytest.approx(1.5)
    assert caption_seconds("x" * 100, 0.07) == pytest.approx(7.0)
