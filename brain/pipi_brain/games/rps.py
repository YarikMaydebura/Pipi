"""Arm rock-paper-scissors (docs/GAMES.md §3.4): "Rock is arms down, paper is arms wide,
scissors is arms crossed. Show me yours and say it!"

One round, in plain words:
1. The robot pumps its fist three times (``rps_shake``) while Pipi counts "Rock... paper...
   scissors...", then shows its random choice (``rps_rock`` / ``rps_paper`` /
   ``rps_scissors``, held) and says "Shoot!".
2. Mode ``voice``: the participant shows their arms AND says the choice; it is matched against
   ``games.yaml -> rps_arms.choice_words``. An unclear answer gets one question; silence for
   ``answer_s`` = the round does not count.
3. Pipi announces who won the round and lets go of the held pose. Best of ``rounds`` (draws
   and rounds without an answer give no point).

Mode ``camera`` (the robot reads the arms with ``gpt-5-nano`` from webcam frames) is not built
yet: until then the game always plays by voice and logs that as ``game_fallback``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Literal

from pipi_brain.games.base import Game, GameContext, RoundResult, Winner
from pipi_brain.games.config import RpsArmsConfig
from pipi_brain.games.registry import contains_phrase, game_info

Choice = Literal["rock", "paper", "scissors"]
CHOICES: tuple[Choice, ...] = ("rock", "paper", "scissors")
BEATS: Mapping[Choice, Choice] = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
SHAKES = 3
SHAKE_S = 0.65  # one rps_shake beat on the fake robot (web/src/fake-robot/gameMotions.ts)
MOTIONS = frozenset({"rps_shake", "rps_rock", "rps_paper", "rps_scissors", "idle"})


def judge(you: Choice, me: Choice) -> Winner | None:
    """Who wins a round (None = draw)."""
    if you == me:
        return None
    return "participant" if BEATS[you] == me else "robot"


def parse_choice(text: str, words: Mapping[str, Sequence[str]]) -> Choice | None:
    """The one choice named in ``text``; None if none or several different ones."""
    found = {
        choice
        for choice in CHOICES
        if any(contains_phrase(text, word) for word in words.get(choice, ()))
    }
    return found.pop() if len(found) == 1 else None


class RockPaperScissors(Game):
    info = game_info("rps_arms")
    has_fallback = True  # voice mode needs no camera

    def __init__(self, config: RpsArmsConfig) -> None:
        self._config = config
        self._score: dict[Winner, int] = {"participant": 0, "robot": 0}

    @property
    def variant(self) -> str:
        return "voice"

    @property
    def wins_needed(self) -> int:
        return self._config.rounds // 2 + 1

    def motions(self) -> frozenset[str]:
        return MOTIONS

    def rounds(self, mode: str) -> int:
        return self._config.rounds

    def start(self, ctx: GameContext) -> None:
        self._score = {"participant": 0, "robot": 0}
        if self._config.mode == "camera":
            ctx.log(
                "game_fallback",
                {
                    "game": self.id,
                    "from": "camera",
                    "to": "voice",
                    "reason": "camera mode not built yet",
                },
            )

    async def fallback_mode(self, ctx: GameContext) -> bool:
        return True  # voice mode is always possible

    async def explain(self, ctx: GameContext) -> None:
        await ctx.say_line("rps_rules", gesture="excited", expression="happy")

    def finished(self, results: Sequence[RoundResult]) -> bool:
        return max(self._score.values()) >= self.wins_needed

    async def play_round(self, ctx: GameContext, round_no: int) -> RoundResult:
        me = CHOICES[min(len(CHOICES) - 1, int(ctx.rng.random() * len(CHOICES)))]
        await self._count_down(ctx)
        await ctx.play_motion(f"rps_{me}")
        await ctx.say_line("rps_shoot", expression="determined")
        you = await self._listen_for_choice(ctx)
        winner = judge(you, me) if you is not None else None
        if winner is not None:
            self._score[winner] += 1
        await self._react(ctx, you, me, winner)
        await ctx.rest()  # the robot's choice is held by the body: let go of it
        return self._result(you, me, winner)

    async def _count_down(self, ctx: GameContext) -> None:
        """Three fist pumps while Pipi says "Rock... paper... scissors..."."""

        async def shakes() -> None:
            for _ in range(SHAKES):
                await ctx.play_motion("rps_shake")
                await ctx.wait(SHAKE_S)

        pumping = asyncio.ensure_future(shakes())
        try:
            await ctx.say_line("rps_count", expression="determined")
            await pumping
        finally:
            if not pumping.done():
                pumping.cancel()

    async def _listen_for_choice(self, ctx: GameContext) -> Choice | None:
        asked = False
        while True:
            heard = await ctx.listen(self._config.answer_s, clarify=False)
            if heard is None:
                return None
            choice = parse_choice(heard.text, self._config.choice_words)
            if choice is not None:
                return choice
            if asked:
                return None
            asked = True
            await ctx.say_line("rps_unclear")

    async def _react(
        self, ctx: GameContext, you: Choice | None, me: Choice, winner: Winner | None
    ) -> None:
        if you is None:
            await ctx.say_line("rps_no_answer", expression="sad")
        elif winner == "participant":
            await ctx.say_line("rps_you_win", expression="surprised", you=you, me=me)
        elif winner == "robot":
            await ctx.say_line("rps_robot_wins", expression="happy", you=you, me=me)
        else:
            await ctx.say_line("rps_draw", expression="happy", me=me)

    def _result(self, you: Choice | None, me: Choice, winner: Winner | None) -> RoundResult:
        if you is None:
            result = "no_contest"
        elif winner is None:
            result = "draw"
        else:
            result = f"{winner}_won"
        return RoundResult(
            result=result,
            winner=winner,
            inputs={"you": you, "me": me, "score": dict(self._score)},
            fallback="voice" if self._config.mode == "camera" else None,
        )

    async def finish(self, ctx: GameContext, results: Sequence[RoundResult]) -> str | None:
        yours, mine = self._score["participant"], self._score["robot"]
        score = f"{max(yours, mine)} to {min(yours, mine)}"
        if yours > mine:
            await ctx.say_line("rps_final_you", gesture="bow", expression="happy", score=score)
            return f"You beat me at rock-paper-scissors, {score}!"
        if mine > yours:
            await ctx.say_line(
                "rps_final_robot", gesture="celebrate", expression="happy", score=score
            )
            return f"I beat you at rock-paper-scissors, {score}!"
        await ctx.say_line("rps_final_draw", expression="happy", score=score)
        return f"Our rock-paper-scissors game was a tie, {score}!"
