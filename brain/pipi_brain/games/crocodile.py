"""Crocodile: the robot acts something out, the participant guesses (docs/GAMES.md §3.1).

One round, in plain words:
1. A word is picked ONLY from ``games.yaml -> crocodile.words`` and never twice in a session,
   and only if the active body can act it (motions.yaml: the real robot has fewer moves).
   The LLM may choose among the unused words (while Pipi says "watch closely!"); if it fails
   or answers something that is not in the list, the word is picked at random.
2. Acting: eyes ``determined`` and the word's motion. The fake robot HOLDS (loops) an acting
   motion until the next motion; it is sent again every few seconds anyway, which keeps a
   body with one-shot motions acting too. During the whole acting step Pipi does NOT speak:
   the step runs inside ``ctx.silence(...)``, which blocks every ``say`` in code, and
   listening is quiet (no "say that again?").
3. Each guess is judged: a guess that contains the word or a synonym is correct at once;
   anything else goes to the LLM (``{"correct", "close"}``); if the LLM fails, the keyword
   lists decide. Close -> an encouraging nod; wrong -> a head shake; then the acting goes on.
4. After ``hint_after_wrong`` wrong guesses the hint: the robot stands still, "look!" eyes,
   and shows the motion once more from its start. After ``max_wrong_guesses`` or
   ``round_timeout_s`` Pipi reveals the answer.
5. Correct -> celebrate + praise line. Only now Pipi talks again. The celebrate / shrug
   motion also ends the held acting motion.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from pipi_brain.dialogue.schemas import InvalidModelOutput, parse_model
from pipi_brain.games.base import ChatMessage, Game, GameContext, RoundResult
from pipi_brain.games.config import CrocodileConfig, CrocodileWord
from pipi_brain.games.registry import game_info
from pipi_brain.phases.clock import cancel_and_wait

ACTING = "crocodile_acting"
TIME_EPSILON_S = 1e-3
JudgeMethod = Literal["keyword", "llm", "keyword_fallback"]


class GuessVerdict(BaseModel):
    """The guess-judge JSON (docs/PERSONA_AND_PROMPTS.md §5). ``say`` is never spoken."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    correct: bool
    close: bool = False


class WordPick(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    word: str


@dataclass(frozen=True)
class Verdict:
    correct: bool
    close: bool
    method: JudgeMethod


@dataclass(frozen=True)
class _Acting:
    """What happened while the robot was acting (before it is allowed to talk again)."""

    result: Literal["guessed", "revealed", "motion_failed"]
    guesses: tuple[dict[str, Any], ...] = ()
    wrong: int = 0
    hint_given: bool = False
    motion_repeats: int = 0
    reveal_reason: str | None = None


def mentions(text: str, term: str) -> bool:
    """True if ``text`` contains ``term`` as whole words (a plural "s" is fine)."""
    return re.search(rf"\b{re.escape(term.casefold())}(?:s|es)?\b", text.casefold()) is not None


def negated(text: str) -> bool:
    """ "It's not a bird", "no bird": the word is there, but it is not the guess."""
    return re.search(r"\b(?:not|no|never)\b|n't\b", text.casefold()) is not None


def judge_by_keywords(guess: str, word: CrocodileWord) -> tuple[bool, bool]:
    """(correct, close) from the word, its synonyms and its ``close`` list. No LLM.

    A negated sentence is never correct here (the LLM gets to judge it instead).
    """
    named = any(mentions(guess, term) for term in (word.word, *word.synonyms))
    correct = named and not negated(guess)
    close = not correct and any(mentions(guess, term) for term in word.close)
    return correct, close


def build_judge_messages(word: CrocodileWord, guess: str) -> list[ChatMessage]:
    accepted = ", ".join(word.synonyms) or "(none)"
    system = (
        "You judge one guess in a game of charades. Pipi, a small robot, silently acts out: "
        f'"{word.word}". Other answers that also count as correct: {accepted}.\n'
        "The participant's guess comes from speech recognition.\n"
        'Return ONLY valid JSON (no markdown, no extra text): {"correct": true or false, '
        '"close": true or false}\n'
        "- correct: the guess means the target or one of the accepted answers (plurals, verb "
        "forms and small recognition mistakes are fine).\n"
        "- close: not correct, but in the right direction (a related thing or activity).\n"
        '- A question, a comment or "I don\'t know" is neither.'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": guess}]


def build_pick_messages(
    words: Sequence[CrocodileWord], interests: Sequence[str]
) -> list[ChatMessage]:
    likes = ", ".join(interests) or "unknown"
    system = (
        "Pick the next thing that Pipi, a small robot, acts out in a game of charades.\n"
        f"Choose exactly ONE word from this list: {[word.word for word in words]}\n"
        f"The participant likes: {likes}. Prefer a word that fits; otherwise pick any.\n"
        'Return ONLY valid JSON (no markdown, no extra text): {"word": "<a word from the list>"}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": "<pick a word>"}]


class CrocodileRobot(Game):
    info = game_info("crocodile_robot")

    def __init__(self, config: CrocodileConfig) -> None:
        self._config = config
        self.max_rounds = max(config.rounds_study, config.rounds_demo)
        self._used: set[str] = set()  # words already acted in this session
        self._progress: dict[str, Any] = {}  # the running round, for the log if it is cut short

    def motions(self) -> frozenset[str]:
        acting = {word.motion for word in self._config.words}
        return frozenset(acting | {"celebrate", "nod", "shake_head", "shrug", "idle"})

    def can_play(self) -> bool:
        return bool(self._unused())

    def progress(self) -> dict[str, Any]:
        return dict(self._progress)

    def rounds(self, mode: str) -> int:
        return max(1, min(self._config.rounds_for(mode), len(self._unused())))

    async def explain(self, ctx: GameContext) -> None:
        await ctx.say_line("crocodile_rules", gesture="excited", expression="happy")

    async def play_round(self, ctx: GameContext, round_no: int) -> RoundResult:
        # Only words the active body can act (the real robot has fewer moves than the fake one).
        unused = [word for word in self._unused() if ctx.can_play_motion(word.motion)]
        if not unused:
            return RoundResult("no_words_left", abort=True)
        # The word is chosen while Pipi says the intro line: no waiting for the participant.
        pick = asyncio.ensure_future(self._pick_word(ctx, unused))
        try:
            intro = "crocodile_watch" if round_no == 1 else "crocodile_next"
            await ctx.say_line(intro, expression="determined")
            word, picked_by = await pick
        finally:
            await cancel_and_wait([pick])
        self._used.add(word.word)
        self._progress = {"word": word.word, "motion": word.motion, "word_pick": picked_by}
        ctx.note(f"crocodile round {round_no}: acting '{word.word}' ({word.motion})")
        started = ctx.now()
        with ctx.silence(ACTING):  # never say the word while acting: no speech at all
            acting = await self._act(ctx, word, started)
        acting_ms = round((ctx.now() - started) * 1000)
        memory = await self._react(ctx, word, acting)
        return RoundResult(
            result=acting.result,
            winner="participant" if acting.result == "guessed" else None,
            inputs={
                "word": word.word,
                "motion": word.motion,
                "word_pick": picked_by,
                "guesses": list(acting.guesses),
                "wrong_guesses": acting.wrong,
                "hint_given": acting.hint_given,
                "motion_repeats": acting.motion_repeats,
                "reveal_reason": acting.reveal_reason,
            },
            timings={"acting_ms": acting_ms},
            memory=memory,
            abort=acting.result == "motion_failed",
        )

    # --- 1. the word ---------------------------------------------------------------------------

    def _unused(self) -> list[CrocodileWord]:
        return [word for word in self._config.words if word.word not in self._used]

    async def _pick_word(
        self, ctx: GameContext, unused: Sequence[CrocodileWord]
    ) -> tuple[CrocodileWord, str]:
        """(word, "llm" | "random"). The LLM can only choose a word that is in ``unused``."""
        by_name = {word.word.casefold(): word for word in unused}

        def parse(raw: str) -> CrocodileWord:
            name = parse_model(raw, WordPick).word.strip().casefold()
            if name not in by_name:
                raise InvalidModelOutput(f"'{name}' is not one of the unused words")
            return by_name[name]

        if self._config.llm_picks_word and len(unused) > 1:
            interests = [interest.label for interest in ctx.memory.interests]
            picked = await ctx.ask_json(
                build_pick_messages(unused, interests), parse, purpose="crocodile_word"
            )
            if picked is not None:
                return picked, "llm"
        return ctx.rng.choice(list(unused)), "random"

    # --- 2. + 3. acting and guessing (silent) --------------------------------------------------

    async def _act(self, ctx: GameContext, word: CrocodileWord, started: float) -> _Acting:
        config = self._config
        await ctx.set_eyes("determined")
        if not (await ctx.play_motion(word.motion) or await ctx.play_motion(word.motion)):
            return _Acting("motion_failed")
        deadline = started + config.round_timeout_s
        guesses: list[dict[str, Any]] = []
        wrong = 0
        repeats = 0
        hint_given = False
        while True:
            left_s = deadline - ctx.now()
            if left_s <= TIME_EPSILON_S:
                return _Acting(
                    "revealed", tuple(guesses), wrong, hint_given, repeats, reveal_reason="timeout"
                )
            heard = await ctx.listen(
                min(left_s, config.repeat_motion_every_s), eyes="determined", clarify=False
            )
            if heard is None:  # nobody guessed for a while: show it again
                if deadline - ctx.now() > TIME_EPSILON_S:
                    repeats += 1
                    await ctx.play_motion(word.motion)
                continue
            if not heard.understood or not heard.text.strip():
                continue  # a sound we could not understand is not a guess
            verdict = await self._judge(ctx, word, heard.text)
            guesses.append(
                {
                    "text": heard.text,
                    "correct": verdict.correct,
                    "close": verdict.close,
                    "method": verdict.method,
                    "at_ms": round((ctx.now() - started) * 1000),
                }
            )
            self._progress["guesses"] = list(guesses)
            if verdict.correct:
                return _Acting("guessed", tuple(guesses), wrong, hint_given, repeats)
            wrong += 1
            if wrong >= config.max_wrong_guesses:
                return _Acting(
                    "revealed",
                    tuple(guesses),
                    wrong,
                    hint_given,
                    repeats,
                    reveal_reason="max_wrong_guesses",
                )
            await ctx.play_motion("nod" if verdict.close else "shake_head")
            await ctx.wait(config.reaction_pause_s)
            if wrong == config.hint_after_wrong:
                hint_given = True
                await self._hint(ctx)
            await ctx.set_eyes("determined")
            await ctx.play_motion(word.motion)  # the reaction ended the acting: act again

    async def _hint(self, ctx: GameContext) -> None:
        """The hint: stand still, "look!" eyes, then the motion once more from its start."""
        await ctx.play_motion("idle")
        await ctx.set_eyes("surprised")
        await ctx.wait(self._config.reaction_pause_s)

    async def _judge(self, ctx: GameContext, word: CrocodileWord, guess: str) -> Verdict:
        correct, close = judge_by_keywords(guess, word)
        if correct and self._config.keyword_shortcut:
            return Verdict(True, False, "keyword")
        await ctx.set_eyes("thinking")
        answer = await ctx.ask_json(
            build_judge_messages(word, guess),
            lambda raw: parse_model(raw, GuessVerdict),
            purpose="guess_judge",
        )
        if answer is None:  # LLM failed: the word lists decide
            return Verdict(correct, close, "keyword_fallback")
        return Verdict(answer.correct, answer.close and not answer.correct, "llm")

    # --- 4. + 5. reveal or celebrate (Pipi may talk again) -------------------------------------

    async def _react(self, ctx: GameContext, word: CrocodileWord, acting: _Acting) -> str | None:
        """Speak the reaction; returns the moment for memory (as Pipi would say it)."""
        answer = word.spoken
        if acting.result == "motion_failed":
            await ctx.say_line("game_motion_failed", expression="sad")
            return None
        if acting.result == "guessed":
            await ctx.set_eyes("happy")
            await ctx.say_line(
                "crocodile_correct", gesture="celebrate", expression="happy", answer=answer
            )
            tries = acting.wrong + 1
            how = "on the first try" if tries == 1 else f"after {tries} tries"
            return f"You guessed that I was {answer} {how}!"
        await ctx.say_line(
            "crocodile_reveal", gesture="shrug", expression="surprised", answer=answer
        )
        return f"You could not guess that I was {answer}, so I had to tell you."
