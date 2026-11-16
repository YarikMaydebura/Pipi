"""Quick-draw duel (docs/GAMES.md §3.2): "When my eyes turn green, shout BANG!"

One round, in plain words:
1. ``duel_ready`` pose (held by the body), eyes ``countdown``. Pipi is silent from here on.
2. A random wait (``delay_range_s``). A shot during this wait is a false start: the
   participant loses the round.
3. Eyes ``signal_go`` (green). The clock starts when the body has ACKED the green eyes (that
   is when the participant sees them). The fake robot also plays a short "go" sound through
   the laptop speakers, so shots in the first ``go_blank_ms`` after green are ignored (no
   human reacts that fast anyway) and the detector is armed again.
4. Now it is a race between the participant's shot and the robot's own reaction time. The
   robot is a good sport: only with ``robot_win_chance`` it really tries (450-900 ms);
   otherwise it waits (``give_up_s``) and lets the participant win.
5. The loser is hit: the robot falls (``duel_hit``) or celebrates (``duel_draw`` + ``duel_win``).
   These motions also end the held ready pose.
Best of 3 (first to 2 wins); all reaction times are in the ``game_round`` log.

How a "shot" is heard - three variants (``variant``, logged as ``mode``):
- ``detector``: the ``BangDetector`` (loudness spike on raw microphone frames, no STT).
- ``typed``: no microphone (typed session): typing anything + Enter is the bang.
- ``slow_motion``: the detector is missing or unreliable (it fired within ``noise_window_ms``
  after arming = room noise, or the microphone failed): the participant says "bang",
  speech-to-text hears it, and the robot reacts much slower ("slow-motion duel").
The experimenter can always score a round by hand with the existing WoZ command
``play_motion``: ``duel_hit`` = the robot is hit (participant wins the round), ``duel_win`` =
the robot wins.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pipi_brain.games.base import Game, GameContext, RoundResult, Winner
from pipi_brain.games.config import QuickDrawConfig
from pipi_brain.games.registry import contains_phrase, game_info
from pipi_brain.phases.clock import cancel_and_wait
from pipi_brain.speech.bang import BangDetector, BangDetectorError

ShotMode = Literal["detector", "typed", "slow_motion"]
WOZ_SCORES: Mapping[str, Winner] = {"duel_hit": "participant", "duel_win": "robot"}
MAX_REPLAYS = 5  # a round is replayed after a pause or a detector problem; then: no contest
RULES: Mapping[ShotMode, str] = {
    "detector": "quick_draw_rules",
    "typed": "quick_draw_rules_typed",
    "slow_motion": "quick_draw_rules_slow",
}
SWITCH_LINES: Mapping[ShotMode, str] = {
    "typed": "quick_draw_rules_typed",
    "slow_motion": "quick_draw_slow_motion",
}


@dataclass(frozen=True)
class Shot:
    at: float  # on the shot source's clock
    detail: Mapping[str, Any] = field(default_factory=dict)


class ShotSource(Protocol):
    def now(self) -> float: ...

    @property
    def early(self) -> bool:
        """The participant is already making a sound (speech in progress)."""
        ...

    async def next_shot(self) -> Shot: ...


class DetectorShots:
    """Shots from the fast bang detector."""

    early = False

    def __init__(self, detector: BangDetector) -> None:
        self._detector = detector

    def now(self) -> float:
        return self._detector.now()

    async def next_shot(self) -> Shot:
        bang = await self._detector.wait_for_bang()
        return Shot(bang.at, {"level_db": bang.level_db})


class ListenShots:
    """Shots through normal listening: a typed line, or an utterance that says "bang"."""

    def __init__(self, ctx: GameContext, bang_words: Sequence[str]) -> None:
        self._ctx = ctx
        self._bang_words = tuple(bang_words)

    def now(self) -> float:
        return self._ctx.now()

    @property
    def early(self) -> bool:
        return self._ctx.hearing

    async def next_shot(self) -> Shot:
        while True:
            heard = await self._ctx.listen(None, eyes=None, clarify=False, allow_empty=True)
            if heard is None:
                continue
            said_bang = any(contains_phrase(heard.text, word) for word in self._bang_words)
            # Typed: anything counts. Voice: "bang", or a shout the STT could not understand.
            if heard.typed or not heard.understood or said_bang:
                detail = {"heard": heard.text, "understood": heard.understood}
                return Shot(self._ctx.now(), detail)


@dataclass(frozen=True)
class _Duel:
    """One finished duel (a replayed attempt never becomes a _Duel)."""

    winner: Winner | None
    reason: str  # "faster", "false_start", "too_slow", "woz", "no_contest"
    delay_ms: int
    participant_ms: int | None = None  # reaction time after green
    robot_ms: int | None = None  # when the robot drew (or would have drawn)
    false_start_ms: int | None = None  # how long after the countdown started
    robot_played_to_win: bool | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


class _Replay(Exception):
    """This attempt does not count (pause, detector problem): play the round again."""


class _Race:
    """Everything one duel waits for: the shot, a WoZ score, a WoZ pause - and one timer."""

    def __init__(self, ctx: GameContext, shots: ShotSource, delay_ms: int) -> None:
        self.shots = shots
        self.delay_ms = delay_ms
        self.armed_at = shots.now()
        self._ctx = ctx
        self._woz = asyncio.ensure_future(ctx.woz_motion(WOZ_SCORES))
        self._pause = asyncio.ensure_future(ctx.wait_paused())
        self._shot = asyncio.ensure_future(shots.next_shot())
        self._timers: list[asyncio.Future[Any]] = []

    def timer(self, seconds: float) -> asyncio.Future[Any]:
        """A pausable timer that belongs to this duel (cancelled with it)."""
        timer = asyncio.ensure_future(self._ctx.wait(seconds))
        self._timers.append(timer)
        return timer

    async def first(self, timer: asyncio.Future[Any]) -> Literal["woz", "shot", "timer"]:
        """What happens first. A WoZ pause raises ``_Replay`` (the round does not count)."""
        waiting = [self._woz, self._pause, self._shot, timer]
        done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        if self._woz in done:
            return "woz"
        if self._pause in done:
            raise _Replay
        return "shot" if self._shot in done else "timer"

    def shot(self) -> Shot:
        """The shot that just happened (raises BangDetectorError if the detector failed)."""
        shot: Shot = self._shot.result()
        return shot

    def rearm(self) -> None:
        """Listen for the next shot (the last one did not count)."""
        self._shot = asyncio.ensure_future(self.shots.next_shot())

    def scored_by_woz(self) -> _Duel:
        motion: str = self._woz.result()
        return _Duel(WOZ_SCORES[motion], "woz", self.delay_ms, detail={"woz_motion": motion})

    async def close(self) -> None:
        waiting = [self._woz, self._pause, self._shot, *self._timers]
        await cancel_and_wait(waiting)
        for future in waiting:  # e.g. a detector error after the WoZ already scored the round
            if not future.cancelled():
                future.exception()  # mark as seen (asyncio would warn otherwise)


class QuickDraw(Game):
    info = game_info("quick_draw")
    has_fallback = True  # typed / slow-motion variants need no bang detector

    def __init__(self, config: QuickDrawConfig) -> None:
        self._config = config
        self.max_rounds = config.rounds
        self._mode: ShotMode = "detector"
        self._score: dict[Winner, int] = {"participant": 0, "robot": 0}
        self._fallback_reason = "no bang detector"

    @property
    def variant(self) -> str:
        return self._mode

    def motions(self) -> frozenset[str]:
        return frozenset(
            {"duel_ready", "duel_draw", "duel_hit", "duel_win", "bow", "celebrate", "idle"}
        )

    def start(self, ctx: GameContext) -> None:
        self._mode = "detector"
        self._score = {"participant": 0, "robot": 0}
        self._fallback_reason = "no bang detector"

    async def fallback_mode(self, ctx: GameContext) -> bool:
        """No (reliable) bang detector: typing when there is no microphone, else slow motion."""
        new_mode: ShotMode = "typed" if ctx.input_mode == "typed" else "slow_motion"
        ctx.log(
            "game_fallback",
            {"game": self.id, "from": self._mode, "to": new_mode, "reason": self._fallback_reason},
        )
        self._mode = new_mode
        return True

    async def explain(self, ctx: GameContext) -> None:
        await ctx.say_line(RULES[self._mode], gesture="excited", expression="happy")

    def finished(self, results: Sequence[RoundResult]) -> bool:
        return max(self._score.values()) >= self._config.wins_needed

    # --- one round -----------------------------------------------------------------------------

    async def play_round(self, ctx: GameContext, round_no: int) -> RoundResult:
        replays = 0
        while True:
            try:
                duel = await self._duel(ctx, round_no)
                break
            except _Replay:
                replays += 1
                await ctx.rest()  # the ready pose is held by the body: let go of it
                if replays > MAX_REPLAYS:
                    duel = _Duel(None, "no_contest", 0)
                    break
        if duel.winner is not None:
            self._score[duel.winner] += 1
        await self._react(ctx, duel)
        mine, yours = self._score["robot"], self._score["participant"]
        return RoundResult(
            result=f"{duel.winner}_won" if duel.winner else "no_contest",
            winner=duel.winner,
            inputs={
                "shot_by": self._mode,
                "reason": duel.reason,
                "false_start": duel.reason == "false_start",
                "scored_by": "woz" if duel.reason == "woz" else "race",
                "robot_played_to_win": duel.robot_played_to_win,
                "score": {"participant": yours, "robot": mine},
                "replays": replays,
                **duel.detail,
            },
            timings={
                "delay_ms": duel.delay_ms,
                "participant_reaction_ms": duel.participant_ms,
                "robot_reaction_ms": duel.robot_ms,
                "false_start_ms": duel.false_start_ms,
            },
            fallback=None if self._mode == "detector" else self._mode,
        )

    def _shots(self, ctx: GameContext) -> ShotSource:
        detector = ctx.bang_detector
        if self._mode == "detector" and detector is not None:
            return DetectorShots(detector)
        return ListenShots(ctx, self._config.bang_words)

    def progress(self) -> dict[str, Any]:
        return {"shot_by": self._mode, "score": dict(self._score)}

    async def _duel(self, ctx: GameContext, round_no: int) -> _Duel:
        await ctx.wait_running()
        if self._mode == "detector" and ctx.bang_detector is None:
            # The microphone failed since the game started (the session switched to typing).
            await self._switch(ctx, "the bang detector is not available any more")
        await ctx.say_line("quick_draw_round", expression="determined", n=str(round_no))
        await ctx.play_motion("duel_ready")
        await ctx.set_eyes("countdown")
        ctx.note(f"duel round {round_no}: wait for GREEN ({self._mode})")
        delay_s = ctx.rng.uniform(*self._config.delay_range_s)
        race = _Race(ctx, self._shots(ctx), round(delay_s * 1000))
        try:
            early = await self._before_green(ctx, race, delay_s)
            return early if early is not None else await self._after_green(ctx, race)
        finally:
            await race.close()

    async def _before_green(self, ctx: GameContext, race: _Race, delay_s: float) -> _Duel | None:
        """The random wait. Returns the duel if it is already decided (false start, WoZ)."""
        first = await race.first(race.timer(delay_s))
        if first == "woz":
            return race.scored_by_woz()
        if first == "timer" and not race.shots.early:
            return None  # nobody shot: the eyes can turn green
        shot = await self._shot(ctx, race) if first == "shot" else None
        early_ms = round(((shot.at if shot else race.shots.now()) - race.armed_at) * 1000)
        if self._mode == "detector" and early_ms <= self._config.noise_window_ms:
            await self._switch(ctx, f"bang {early_ms} ms after arming (room noise)")
        detail = dict(shot.detail) if shot else {"speaking_at_green": True}
        return _Duel("robot", "false_start", race.delay_ms, false_start_ms=early_ms, detail=detail)

    async def _after_green(self, ctx: GameContext, race: _Race) -> _Duel:
        """Green: the participant's shot against the robot's own reaction time."""
        config, shots = self._config, race.shots
        # The clock starts when the body has ACKED the green eyes: that is when the participant
        # can see them (and when the fake robot plays its short "go" sound).
        sent_at = shots.now()
        green_acked = await ctx.set_eyes("signal_go")
        go_at = shots.now()
        ctx.note("GREEN! shoot!")
        plays_to_win = (not ctx.config.good_sport) or ctx.rng.random() < config.robot_win_chance
        robot_ms = round(self._robot_ms(ctx, plays_to_win))
        draw = race.timer(robot_ms / 1000)
        facts: dict[str, Any] = {"green_acked": green_acked, "ignored_after_green": 0}
        while True:
            first = await race.first(draw)
            if first == "woz":
                return race.scored_by_woz()
            if first == "timer":
                reason = "faster" if plays_to_win else "too_slow"
                return _Duel(
                    "robot",
                    reason,
                    race.delay_ms,
                    robot_ms=robot_ms,
                    robot_played_to_win=plays_to_win,
                    detail=facts,
                )
            shot = await self._shot(ctx, race)
            if shot.at < sent_at:  # fired just before the eyes changed: still a false start
                early_ms = round((shot.at - race.armed_at) * 1000)
                return _Duel(
                    "robot",
                    "false_start",
                    race.delay_ms,
                    false_start_ms=early_ms,
                    detail={**facts, **shot.detail},
                )
            reaction_ms = round((shot.at - go_at) * 1000)
            if reaction_ms >= config.go_blank_ms:
                return _Duel(
                    "participant",
                    "faster",
                    race.delay_ms,
                    participant_ms=reaction_ms,
                    robot_ms=robot_ms,
                    robot_played_to_win=plays_to_win,
                    detail={**facts, **shot.detail},
                )
            # Inside the blanking window: the body's "go" sound in the speakers (or an
            # impossible reaction time), not the participant. Arm again and keep racing.
            facts["ignored_after_green"] += 1
            race.rearm()

    def _robot_ms(self, ctx: GameContext, plays_to_win: bool) -> float:
        """When the robot draws after green: its reaction time, or how long it waits for you."""
        config = self._config
        slow = self._mode == "slow_motion"
        if plays_to_win:
            low, high = config.slow_motion_robot_ms if slow else config.robot_reaction_ms
            return ctx.rng.uniform(low, high)
        return (config.slow_motion_give_up_s if slow else config.give_up_s) * 1000

    async def _shot(self, ctx: GameContext, race: _Race) -> Shot:
        """The shot that just happened; a detector failure switches to the fallback (replay)."""
        try:
            return race.shot()
        except BangDetectorError as exc:
            await self._switch(ctx, f"bang detector failed: {exc}")
            raise AssertionError("unreachable") from exc

    async def _switch(self, ctx: GameContext, reason: str) -> None:
        """The detector is unreliable: announce the fallback variant and replay the round."""
        self._fallback_reason = reason
        await self.fallback_mode(ctx)
        await ctx.rest()  # leave the held ready pose while Pipi explains
        await ctx.say_line(SWITCH_LINES[self._mode], expression="surprised")
        raise _Replay

    # --- reactions -----------------------------------------------------------------------------

    async def _react(self, ctx: GameContext, duel: _Duel) -> None:
        by_woz = duel.reason == "woz"  # the experimenter already played the motion
        if duel.winner == "participant":
            if not by_woz:
                await ctx.play_motion("duel_hit")
            await ctx.say_line("quick_draw_you_win", expression="surprised")
        elif duel.winner == "robot":
            if not by_woz:
                await ctx.play_motion("duel_draw")
                await ctx.play_motion("duel_win")
            line = {
                "false_start": "quick_draw_false_start",
                "too_slow": "quick_draw_too_slow",
            }.get(duel.reason, "quick_draw_robot_wins")
            await ctx.say_line(line, expression="happy")
        else:
            await ctx.rest()
            await ctx.say_line("quick_draw_no_contest", expression="surprised")

    async def finish(self, ctx: GameContext, results: Sequence[RoundResult]) -> str | None:
        yours, mine = self._score["participant"], self._score["robot"]
        if yours > mine:
            score = f"{yours} to {mine}"
            await ctx.say_line(
                "quick_draw_final_you", gesture="bow", expression="happy", score=score
            )
            return f"You beat me in the quick-draw duel, {score}!"
        if mine > yours:
            score = f"{mine} to {yours}"
            await ctx.say_line(
                "quick_draw_final_robot", gesture="celebrate", expression="happy", score=score
            )
            return f"I won our quick-draw duel, {score}."
        return f"Our quick-draw duel ended {yours} to {mine}."
