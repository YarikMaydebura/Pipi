"""LLM dialogue turn: gpt-5-nano -> validated JSON, with retry and a scripted fallback.

``ChatModel`` is the interface (real: :class:`OpenAIChatModel`, fake: ``fakes.FakeChatModel``).
:class:`DialogueEngine` adds the robustness rules from docs/SYSTEM_DESIGN.md 4.4:
timeout per attempt -> invalid JSON or error -> one retry -> scripted fallback line.
It never raises; every failed attempt is reported in ``DialogueResult.errors`` for the log.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

from pipi_brain.config import ReasoningEffort
from pipi_brain.dialogue.prompts import ChatMessage
from pipi_brain.dialogue.schemas import DialogueTurn, InvalidModelOutput, parse_dialogue_turn
from pipi_brain.resilience import elapsed_ms_since, timed_call

if TYPE_CHECKING:
    from openai import AsyncOpenAI

T = TypeVar("T")


class LlmError(Exception):
    """The model call itself failed in a way the SDK did not raise (e.g. empty answer)."""


class ChatModel(Protocol):
    async def complete_json(self, messages: Sequence[ChatMessage]) -> str:
        """Return the raw text of the model's JSON answer."""
        ...


class OpenAIChatModel:
    """gpt-5-nano via Chat Completions in JSON mode.

    gpt-5-nano is a reasoning model: it rejects ``temperature``, so we do not send it, and we
    use the reasoning effort from config (``minimal`` = fastest). ``max_completion_tokens``
    includes the hidden reasoning tokens.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        reasoning_effort: ReasoningEffort,
        max_output_tokens: int,
    ) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens

    async def complete_json(self, messages: Sequence[ChatMessage]) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=list(messages),  # type: ignore[arg-type]  # plain role/content dicts
            reasoning_effort=self._reasoning_effort,
            response_format={"type": "json_object"},
            max_completion_tokens=self._max_output_tokens,
        )
        if not response.choices:
            raise LlmError("response has no choices")
        choice = response.choices[0]
        content = choice.message.content
        if not content:
            raise LlmError(f"empty answer (finish_reason={choice.finish_reason})")
        return content


@dataclass(frozen=True)
class DialogueResult:
    turn: DialogueTurn
    fallback_used: bool
    attempts: int
    errors: tuple[str, ...]  # one entry per failed attempt, already secret-free
    llm_ms: int  # wall time of all attempts together


@dataclass(frozen=True)
class JsonResult(Generic[T]):
    """Outcome of ``DialogueEngine.ask``: ``value`` is None when every attempt failed."""

    value: T | None
    attempts: int
    errors: tuple[str, ...]  # one entry per failed attempt, already secret-free
    llm_ms: int


class DialogueEngine:
    def __init__(self, model: ChatModel, *, timeout_s: float, retries: int) -> None:
        self._model = model
        self._timeout_s = timeout_s
        self._retries = retries

    async def ask(
        self,
        messages: Sequence[ChatMessage],
        parse: Callable[[str], T],
        *,
        timeout_s: float | None = None,
        retries: int | None = None,
    ) -> JsonResult[T]:
        """One JSON answer, validated by ``parse`` (raises InvalidModelOutput when wrong).

        Timeout per attempt; an error or an invalid answer is retried ``retries`` times.
        Never raises: the caller checks ``value`` and uses its own fallback.
        """
        start = time.perf_counter()
        errors: list[str] = []
        attempts = 0
        limit_s = self._timeout_s if timeout_s is None else timeout_s
        for _ in range(1 + (self._retries if retries is None else retries)):
            attempts += 1
            outcome = await timed_call(lambda: self._model.complete_json(messages), limit_s)
            if not outcome.ok or outcome.value is None:
                errors.append(outcome.error or "no answer")
                continue
            try:
                value = parse(outcome.value)
            except InvalidModelOutput as exc:
                errors.append(f"invalid output: {exc}")
                continue
            return JsonResult(value, attempts, tuple(errors), elapsed_ms_since(start))
        return JsonResult(None, attempts, tuple(errors), elapsed_ms_since(start))

    async def respond(self, messages: Sequence[ChatMessage], fallback_line: str) -> DialogueResult:
        result = await self.ask(messages, parse_dialogue_turn)
        if result.value is not None:
            return DialogueResult(
                result.value, False, result.attempts, result.errors, result.llm_ms
            )
        fallback = DialogueTurn(say=fallback_line, expression="idle", gesture="none")
        return DialogueResult(fallback, True, result.attempts, result.errors, result.llm_ms)
