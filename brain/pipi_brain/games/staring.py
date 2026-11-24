"""Staring contest (docs/GAMES.md §3.3): "Look into my eyes. The first one to blink loses."

One round, in plain words:
1. ``stare_ready`` pose (held by the body), eyes ``determined``, "Ready... go!", then Pipi is
   silent until the round is decided.
2. A race between:
   - the participant's blink, seen by the webcam (``BlinkDetector``, mode ``detect``),
   - the participant admitting it ("I blinked", heard by voice or typed),
   - the robot giving up on purpose after a random ``robot_loses_after_s`` (it is a good
     sport: without a blink the participant always wins in the end),
   - the experimenter scoring by hand with WoZ ``play_motion``: ``stare_lose`` = the robot
     lost, ``celebrate`` = the robot won.
3. The robot loses (``stare_lose``, "Argh! My eyes!") or wins (``celebrate``).

Mode ``pretend`` (fallback, logged as ``game_fallback``): no webcam, no face in view, too few
frames per second, or the camera dies during the round. Then only admitting, the robot giving
up and the WoZ decide. Camera frames never leave the detector (privacy: vision/base.py).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pipi_brain.games.base import Game, GameContext, RoundResult, Winner
from pipi_brain.games.config import StaringConfig
from pipi_brain.games.registry import contains_phrase, game_info
from pipi_brain.phases.clock import cancel_and_wait
from pipi_brain.resilience import describe_error

StareMode = Literal["detect", "pretend"]
WOZ_SCORES: Mapping[str, Winner] = {"stare_lose": "participant", "celebrate": "robot"}
ADMIT_PHRASES = ("blinked", "i blink", "i lost", "you win", "you won")
MOTIONS = frozenset({"stare_ready", "stare_lose", "celebrate"})


@dataclass(frozen=True)
class _Stare:
    winner: Winner
    how: str  # blink_detected | admitted | robot_gave_up | woz
    after_s: float  # seconds after "go"
    heard: str | None = None


class Staring(Game):
    info = game_info("staring")
    has_fallback = True  # pretend mode needs no camera
    max_rounds = 1

    def __init__(self, config: StaringConfig) -> None:
        self._config = config
        self._mode: StareMode = "detect"

    @property
    def variant(self) -> str:
        return self._mode

    def motions(self) -> frozenset[str]:
        return MOTIONS

    def start(self, ctx: GameContext) -> None:
        self._mode = "detect"

    async def fallback_mode(self, ctx: GameContext) -> bool:
        self._switch(ctx, "no camera")
        return True

    def _switch(self, ctx: GameContext, reason: str) -> None:
        if self._mode == "pretend":
            return
        ctx.log(
            "game_fallback", {"game": self.id, "from": "detect", "to": "pretend", "reason": reason}
        )
        ctx.note(f"staring contest: pretend mode ({reason})")
        self._mode = "pretend"

    async def explain(self, ctx: GameContext) -> None:
        detector = ctx.blink_detector
        if self._mode == "detect" and detector is not None:
            check = await detector.check()
            if not check.ok:
                self._switch(ctx, check.reason or f"{check.fps:g} fps")
        rules = "staring_rules" if self._mode == "detect" else "staring_rules_pretend"
        await ctx.say_line(rules, gesture="excited", expression="happy")

    async def play_round(self, ctx: GameContext, round_no: int) -> RoundResult:
        try:
            await ctx.play_motion("stare_ready")
            await ctx.set_eyes("determined")
            await ctx.say_line("staring_go", expression="determined")
            gives_up_s = ctx.rng.uniform(*self._config.robot_loses_after_s)
            with ctx.silence("staring"):
                stare = await self._stare(ctx, gives_up_s)
            await self._react(ctx, stare)
        finally:
            await self._release_camera(ctx)
        return self._result(stare)

    async def _stare(self, ctx: GameContext, gives_up_s: float) -> _Stare:
        started = ctx.now()
        waits: dict[str, asyncio.Future[Any]] = {
            "robot_gave_up": asyncio.ensure_future(ctx.wait(gives_up_s)),
            "admitted": asyncio.ensure_future(self._admission(ctx)),
            "woz": asyncio.ensure_future(ctx.woz_motion(WOZ_SCORES)),
        }
        detector = ctx.blink_detector
        if self._mode == "detect" and detector is not None:
            waits["blink_detected"] = asyncio.ensure_future(detector.wait_for_blink())
        try:
            while True:
                done, _ = await asyncio.wait(waits.values(), return_when=asyncio.FIRST_COMPLETED)
                how, task = next((h, t) for h, t in waits.items() if t in done)
                if how == "blink_detected" and task.exception() is not None:
                    self._switch(ctx, describe_error(task.exception()))  # camera died: pretend
                    del waits[how]
                    continue
                return self._decided(how, task.result(), ctx.now() - started)
        finally:
            await cancel_and_wait(waits.values())

    @staticmethod
    def _decided(how: str, value: Any, after_s: float) -> _Stare:
        if how == "woz":
            return _Stare(WOZ_SCORES[value], "woz", after_s)
        if how == "robot_gave_up":
            return _Stare("participant", how, after_s)
        heard = value if how == "admitted" else None
        return _Stare("robot", how, after_s, heard=heard)

    async def _admission(self, ctx: GameContext) -> str:
        """Listen (silently) until the participant says they blinked."""
        while True:
            heard = await ctx.listen(None, eyes=None, clarify=False)
            if heard is None or not heard.understood:
                continue
            if any(contains_phrase(heard.text, phrase) for phrase in ADMIT_PHRASES):
                return heard.text

    async def _react(self, ctx: GameContext, stare: _Stare) -> None:
        if stare.winner == "participant":
            await ctx.play_motion("stare_lose")
            await ctx.say_line("staring_you_win", expression="surprised")
            return
        await ctx.play_motion("celebrate")
        line = "staring_admitted" if stare.how == "admitted" else "staring_you_blinked"
        await ctx.say_line(line, expression="happy")

    async def _release_camera(self, ctx: GameContext) -> None:
        detector = ctx.blink_detector
        if detector is not None:
            with contextlib.suppress(Exception):
                await asyncio.shield(detector.close())

    def _result(self, stare: _Stare) -> RoundResult:
        timing_key = {
            "blink_detected": "blink_ms",
            "admitted": "admitted_ms",
            "robot_gave_up": "robot_gave_up_ms",
            "woz": "woz_ms",
        }[stare.how]
        memory = (
            "You won our staring contest: my eyes gave up first!"
            if stare.winner == "participant"
            else "You blinked first in our staring contest!"
        )
        return RoundResult(
            result=f"{stare.winner}_won",
            winner=stare.winner,
            inputs={"how": stare.how, "mode": self._mode, "heard": stare.heard},
            timings={timing_key: round(stare.after_s * 1000)},
            fallback="pretend" if self._mode == "pretend" else None,
            memory=memory,
        )
