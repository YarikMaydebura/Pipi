"""The three M3 parts together: the real session controller behind the real WoZ server,
driven by a real WebSocket client that plays the panel (fake speech parts and bodies)."""

from __future__ import annotations

import asyncio
import functools
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.fakes import FakeChatModel, FakeSpeaker, FakeSpeechToText, FakeTextToSpeech
from pipi_brain.protocol import BRAIN_TO_WOZ, WozCommand, encode
from pipi_brain.session_app import SessionAppOptions, run_session
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.voice_app import SessionOptions
from pipi_brain.voice_loop import VoiceLoopDeps
from pipi_brain.woz_api import WozBackend
from pipi_brain.woz_server import WozServer, serve_woz

from .session_harness import app_with
from .test_session_app import FakeHost, folder

STEP_TIMEOUT_S = 5.0


class SilentParticipant:
    """A participant who never types: the session only moves when the panel says so."""

    async def read_line(self) -> str | None:
        await asyncio.Event().wait()
        return None


async def silent_deps(
    loaded: LoadedConfig, options: SessionOptions, gate: AudioGate
) -> tuple[VoiceLoopDeps, dict[str, str]]:
    deps = VoiceLoopDeps(
        stt=FakeSpeechToText(),
        tts=FakeTextToSpeech(),
        speaker=FakeSpeaker(),
        dialogue=DialogueEngine(FakeChatModel(), timeout_s=1, retries=0),
        text_input=SilentParticipant(),
        audio_input=None,
    )
    return deps, {"openai_key": "set", "microphone": "not used (typed input)"}


async def next_of(client: Any, kind: str, **match: Any) -> dict[str, Any]:
    """Read frames (each must be a valid brain->WoZ message) until one matches."""
    while True:
        raw = await asyncio.wait_for(client.recv(), STEP_TIMEOUT_S)
        BRAIN_TO_WOZ.validate_json(raw)
        frame = json.loads(raw)
        if frame["type"] == kind and all(frame.get(k) == v for k, v in match.items()):
            return frame


async def play_panel(port: int, seen: dict[str, Any]) -> None:
    async with connect(f"ws://127.0.0.1:{port}/ws/woz") as panel:
        seen["first"] = await next_of(panel, "state_update")
        wrong = WozCommand(
            command="start_session", args={"participant_id": "P99"}, reason="other", note="test"
        )
        await panel.send(encode(wrong))
        seen["wrong_id_ack"] = await next_of(panel, "ack", ref_id=wrong.id)
        start = WozCommand(
            command="start_session", args={"participant_id": "P07"}, reason="other", note="test"
        )
        await panel.send(encode(start))
        seen["start_ack"] = await next_of(panel, "ack", ref_id=start.id)
        seen["running"] = await next_of(panel, "state_update", phase="GREETING")
        bad = WozCommand(command="goto_phase", args={"phase": "LUNCH"}, reason="timing")
        await panel.send(encode(bad))
        seen["bad_ack"] = await next_of(panel, "ack", ref_id=bad.id)
        end = WozCommand(command="end_session", reason="timing")
        await panel.send(encode(end))
        seen["end_ack"] = await next_of(panel, "ack", ref_id=end.id)


async def test_panel_starts_steers_and_ends_a_real_session(
    dev_config: LoadedConfig, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    (dist / "woz").mkdir(parents=True)
    (dist / "woz" / "index.html").write_text("<!doctype html><title>WoZ</title>", "utf-8")
    app = app_with(
        dev_config.app,
        tts_cache={"dir": tmp_path / "tts"},
        bodies={"connect_wait_s": 0},
        woz={"web_dist": dist},
    )
    # port 0 = any free port (the real config requires >= 1024), so skip validation here
    app = app.model_copy(update={"woz": app.woz.model_copy(update={"port": 0})})
    loaded = replace(dev_config, app=app)
    seen: dict[str, Any] = {}
    panel_task: list[asyncio.Task[None]] = []

    @asynccontextmanager
    async def woz_with_panel(backend: WozBackend, *, log: Any) -> AsyncIterator[WozServer]:
        factory = functools.partial(serve_woz, loaded=loaded, announce=lambda _: None)
        async with factory(backend, log=log) as server:
            panel_task.append(asyncio.create_task(play_panel(server.port, seen)))
            yield server

    summary = await asyncio.wait_for(
        run_session(
            loaded,
            SessionAppOptions(participant_id="P07", typed_input=True, persona_id="calm"),
            woz_server_factory=woz_with_panel,
            deps_factory=silent_deps,
            body_host_factory=lambda *_: FakeHost(),
            emit=lambda _: None,
        ),
        timeout=30,
    )
    await asyncio.wait_for(panel_task[0], STEP_TIMEOUT_S)

    assert seen["first"]["phase"] == "SETUP"  # waits for the experimenter
    assert seen["wrong_id_ack"]["ok"] is False  # the log folder is already named P07
    assert seen["start_ack"]["ok"] is True
    assert seen["running"]["participant_id"] == "P07"
    assert seen["bad_ack"]["ok"] is False and "phase" in seen["bad_ack"]["error"]
    assert seen["end_ack"]["ok"] is True
    assert summary["final_phase"] == "END"
    events = (folder(loaded) / "events.jsonl").read_text("utf-8")
    for needed in (
        '"woz_connected"',
        '"woz_command"',
        '"woz_action"',
        '"phase_change"',
        '"session_end"',
    ):
        assert needed in events
    assert '"reason": "timing"' in events  # every command is logged with its reason
