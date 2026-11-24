"""Shared setup for the session tests: a SessionController on fakes with virtual time."""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipi_brain.config import AppConfig, LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.dialogue.llm import DialogueEngine
from pipi_brain.dialogue.prompts import ChatMessage
from pipi_brain.fakes import (
    FakeBangDetector,
    FakeBlinkDetector,
    FakeBody,
    FakeClock,
    FakeSpeaker,
    FakeSpeechToText,
    FakeTextToSpeech,
    FakeUserInput,
)
from pipi_brain.games.base import GameOutcome
from pipi_brain.games.runner import run_game
from pipi_brain.logging_study import StudyLogger
from pipi_brain.phases.controller import SessionController, SessionDeps
from pipi_brain.phases.game_context import SessionGameContext
from pipi_brain.protocol import BrainToWoz, WozCommand
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.tts_cache import TtsCache
from pipi_brain.vision.base import VisionCheck
from pipi_brain.woz_api import CommandOutcome

REAL_TIMEOUT_S = 10  # a test session must finish within this much REAL time


def turn(say: str, **extra: Any) -> str:
    return json.dumps({"say": say, "expression": "happy", "gesture": "nod", **extra})


@dataclass
class ScriptedChat:
    """LLM fake: scripted answers first, then a harmless default turn forever."""

    answers: list[object] = field(default_factory=list)
    default: str = turn("Nice!")
    delay_s: float = 0.0
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def complete_json(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        await asyncio.sleep(self.delay_s)
        if self.answers:
            item = self.answers.pop(0)
            if isinstance(item, BaseException):
                raise item
            return str(item)
        return self.default


class ScriptedRng(random.Random):
    """The games' randomness, scripted: every draw is predictable in a test.

    ``uniform`` pops from ``uniforms`` (else the middle of the range), ``random`` pops from
    ``randoms`` (else 0.99 = "the robot lets you win"), ``choice`` takes the first item.
    """

    def __init__(self, uniforms: Sequence[float] = (), randoms: Sequence[float] = ()) -> None:
        super().__init__(0)
        self.uniforms = list(uniforms)
        self.randoms = list(randoms)

    def uniform(self, a: float, b: float) -> float:
        return self.uniforms.pop(0) if self.uniforms else (a + b) / 2

    def random(self) -> float:
        return self.randoms.pop(0) if self.randoms else 0.99

    def choice(self, seq: Any) -> Any:
        return seq[0]


def app_with(app: AppConfig, **sections: dict[str, Any]) -> AppConfig:
    """Copy of ``app`` with some fields of some sections replaced, e.g. session={...}."""
    update = {
        name: getattr(app, name).model_copy(update=values) for name, values in sections.items()
    }
    return app.model_copy(update=update)


FAST = {
    "session": {
        "persona_pick_s": 15,
        "greeting_max_s": 60,
        "chat_max_s": 30,
        "game_menu_s": 10,
        "return_end_s": 5,
        "flight_s": 0.8,
        "robot_connect_wait_s": 0,
        "health_poll_s": 1,
        "game_loop": False,
    },
    "timers": {"focus_s": 30, "focus_precue_s": 20, "break_max_s": 300, "silence_reprompt_s": 12},
    "tts_cache": {"enabled": False},
}


@dataclass
class Session:
    ctl: SessionController
    clock: FakeClock
    pet: FakeBody
    robot: FakeBody
    user: FakeUserInput
    chat: ScriptedChat
    stt: FakeSpeechToText
    tts: FakeTextToSpeech
    speaker: FakeSpeaker
    logger: StudyLogger
    rng: ScriptedRng = field(default_factory=ScriptedRng)
    bang: FakeBangDetector | None = None
    blink: FakeBlinkDetector | None = None
    pushed: list[BrainToWoz] = field(default_factory=list)

    async def run(self) -> dict[str, Any]:
        jumper = asyncio.ensure_future(self.clock.autojump())
        try:
            return await asyncio.wait_for(self.ctl.run(), REAL_TIMEOUT_S)
        finally:
            jumper.cancel()

    def start(self) -> asyncio.Task[dict[str, Any]]:
        """Run in the background (for WoZ tests); also starts virtual time."""
        jumper = asyncio.ensure_future(self.clock.autojump())
        task = asyncio.ensure_future(self.ctl.run())
        task.add_done_callback(lambda _: jumper.cancel())
        return task

    async def woz(self, command: str, reason: str = "timing", **args: Any) -> CommandOutcome:
        note = "test" if reason == "other" else None
        return await self.ctl.handle_woz(
            WozCommand(command=command, args=args, reason=reason, note=note)  # type: ignore[arg-type]
        )

    async def until_phase(self, phase: str) -> None:
        for _ in range(1_000_000):
            if self.ctl.state.phase == phase:
                return
            await asyncio.sleep(0)
        raise AssertionError(f"session never reached {phase} (now {self.ctl.state.phase})")

    def events(self, event_type: str | None = None) -> list[dict[str, Any]]:
        return [
            e for e in self.logger.read_events() if event_type is None or e["type"] == event_type
        ]

    def data(self, event_type: str) -> list[dict[str, Any]]:
        return [e["data"] for e in self.events(event_type)]

    def phases(self) -> list[str]:
        return [d["to"] for d in self.data("phase_change")]

    def pipi_lines(self) -> list[str]:
        return [d.get("line_id", "") for d in self.data("turn") if d["speaker"] == "pipi"]

    def pipi_said(self) -> list[str]:
        return [d["text"] for d in self.data("turn") if d["speaker"] == "pipi"]


def make_session(
    loaded: LoadedConfig,
    content: DialogueContent,
    tmp_path: Path,
    *,
    script: list[object] | None = None,
    llm: list[object] | None = None,
    robot_connected: bool = True,
    pet_connected: bool = True,
    auto_start: bool = True,
    mode: str | None = None,
    tts_cache_dir: Path | None = None,
    bodies: dict[str, Any] | None = None,
    bang: list[object] | None = None,
    blink: list[object] | None = None,
    vision: VisionCheck | None = None,
    voice: bool = False,
    rng: ScriptedRng | None = None,
    **overrides: dict[str, Any],
) -> Session:
    """``bang``: script of a FakeBangDetector (implies a microphone session, ``voice``)."""
    sections = {name: dict(values) for name, values in FAST.items()}
    for name, values in overrides.items():
        sections[name] = {**sections.get(name, {}), **values}
    app = app_with(loaded.app, **sections)
    if mode is not None:
        app = app.model_copy(update={"mode": mode})
    clock = FakeClock()
    pet = FakeBody(name="desktop_pet", connected=pet_connected)
    robot = FakeBody(name="fake_robot", connected=robot_connected)
    has_mic = voice or bang is not None
    user = FakeUserInput(
        script=list(script or []), clock=clock, mode="voice" if has_mic else "typed"
    )
    detector = FakeBangDetector(clock, list(bang)) if bang is not None else None
    blinker = (
        FakeBlinkDetector(clock, list(blink), vision=vision or VisionCheck(ok=True, fps=30))
        if blink is not None
        else None
    )
    rng = rng or ScriptedRng()
    chat = ScriptedChat(list(llm or []))
    stt, tts, speaker = FakeSpeechToText(), FakeTextToSpeech(), FakeSpeaker()
    logger = StudyLogger(app.logging.dir, "P01")
    cache = (
        TtsCache(
            tts_cache_dir,
            tts=tts,
            model="gpt-4o-mini-tts",
            voice="nova",
            timeout_s=1,
            on_error=lambda kind, data: logger.log(kind, data),
        )
        if tts_cache_dir is not None
        else None
    )
    ctl = SessionController(
        app=app,
        content=content,
        logger=logger,
        deps=SessionDeps(
            stt=stt,
            tts=tts,
            speaker=speaker,
            dialogue=DialogueEngine(chat, timeout_s=1, retries=1),
            input=user,  # type: ignore[arg-type]
            bodies=bodies if bodies is not None else {"desktop_pet": pet, "fake_robot": robot},
            gate=AudioGate(0),
            clock=clock,
            tts_cache=cache,
            bang_detector=detector,
            blink_detector=blinker,
            rng=rng,
        ),
        participant_id="P01",
        auto_start=auto_start,
        emit=lambda _: None,
    )
    session = Session(
        ctl,
        clock,
        pet,
        robot,
        user,
        chat,
        stt,
        tts,
        speaker,
        logger,
        rng=rng,
        bang=detector,
        blink=blinker,
    )
    ctl.subscribe(session.pushed.append)
    return session


@dataclass
class GameTable:
    """One game played directly (no phases around it), on the real session context."""

    s: Session
    ctx: SessionGameContext

    async def play(self, game_id: str, meanwhile: Any = None) -> GameOutcome:
        """Play one game; ``meanwhile`` (a coroutine, e.g. the experimenter) runs alongside."""
        game = self.s.ctl.registry.implementation(game_id)
        assert game is not None, f"{game_id} is not registered"
        playing = run_game(game, self.ctx, registry=self.s.ctl.registry)
        if meanwhile is None:
            return await self.run(playing)
        outcome, _ = await self.run(asyncio.gather(playing, meanwhile))
        return outcome

    async def run(self, work: Any) -> Any:
        """Await ``work`` with virtual time running."""
        jumper = asyncio.ensure_future(self.s.clock.autojump())
        try:
            return await asyncio.wait_for(work, REAL_TIMEOUT_S)
        finally:
            jumper.cancel()

    def robot_did(self, *kinds: str) -> list[tuple[str, object]]:
        """What the robot body was asked to do, e.g. robot_did("motion", "speak")."""
        return [call for call in self.s.robot.calls if not kinds or call[0] in kinds]

    def rounds(self) -> list[dict[str, Any]]:
        return self.s.data("game_round")


async def make_game_table(
    loaded: LoadedConfig, content: DialogueContent, tmp_path: Path, **kw: Any
) -> GameTable:
    """A session whose robot body is already awake: ready to play a game on it."""
    session = make_session(loaded, content, tmp_path, **kw)
    table = GameTable(session, SessionGameContext(session.ctl.ctx))

    async def no_announcement(_: Any) -> None:
        return None

    result = await table.run(session.ctl.bodies.migrate_out(no_announcement))
    assert result.success
    session.robot.calls.clear()
    return table
