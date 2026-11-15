"""Memory, JSON validation, prompt building, content loading, LLM engine fallbacks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pipi_brain.config import ConfigError, DialogueConfig
from pipi_brain.dialogue.content import DialogueContent, load_dialogue_content
from pipi_brain.dialogue.llm import DialogueEngine, LlmError, OpenAIChatModel
from pipi_brain.dialogue.prompts import ConversationTurn, build_context, build_messages
from pipi_brain.dialogue.schemas import InvalidModelOutput, parse_dialogue_turn
from pipi_brain.fakes import FakeChatModel
from pipi_brain.memory import Memory, MemoryUpdates

VALID = json.dumps(
    {
        "say": "Nice to meet you, Lena!",
        "expression": "happy",
        "gesture": "wave",
        "memory_updates": {"name": "Lena", "interests": [], "reading_feeling": None},
        "needs_clarification": False,
    }
)

# --- memory ---------------------------------------------------------------------------------


def test_apply_returns_new_memory_and_leaves_original_untouched() -> None:
    memory = Memory(participant_id="P01", persona="cheerful")
    updated, changed = memory.apply(MemoryUpdates(name="Lena", interests=("Elden Ring",)))
    assert memory.name is None and memory.interests == ()
    assert updated.name == "Lena"
    assert [i.label for i in updated.interests] == ["Elden Ring"]
    assert changed == ["name", "interests"]


def test_interests_are_deduplicated_case_insensitively_and_keep_the_quote() -> None:
    memory, _ = Memory(participant_id="P01", persona="calm").apply(
        MemoryUpdates(interests=["Chess"], quote="I love chess")
    )
    again, changed = memory.apply(MemoryUpdates(interests=["chess", "Running"]))
    assert [i.label for i in again.interests] == ["Chess", "Running"]
    assert again.interests[0].quote == "I love chess"
    assert changed == ["interests"]


def test_empty_updates_change_nothing() -> None:
    memory = Memory(participant_id="P01", persona="calm")
    same, changed = memory.apply(MemoryUpdates(name="  ", interests=[""], reading_feeling=""))
    assert same is memory and changed == []


def test_quote_without_new_interest_goes_to_notable_quotes() -> None:
    memory, changed = Memory(participant_id="P01", persona="calm").apply(
        MemoryUpdates(quote="you look like a tiny astronaut")
    )
    assert memory.notable_quotes == ("you look like a tiny astronaut",)
    assert changed == ["notable_quotes"]


def test_memory_updates_are_lenient() -> None:
    updates = MemoryUpdates.model_validate(
        {"name": "x" * 100, "interests": "football", "unknown_key": 1}
    )
    assert len(updates.name or "") == 40
    assert updates.interests == ("football",)


def test_greeting_complete_needs_name_interest_and_feeling() -> None:
    memory = Memory(participant_id="P01", persona="calm")
    memory, _ = memory.apply(MemoryUpdates(name="Lena", interests=["chess"]))
    assert not memory.greeting_complete
    memory, _ = memory.apply(MemoryUpdates(reading_feeling="a bit tired"))
    assert memory.greeting_complete


def test_memory_summary_mentions_known_and_unknown_facts() -> None:
    memory, _ = Memory(participant_id="P01", persona="calm").apply(
        MemoryUpdates(name="Lena", interests=["Elden Ring"], quote="I play it a lot")
    )
    summary = memory.summary_for_prompt()
    assert "Lena" in summary
    assert 'Elden Ring ("I play it a lot")' in summary
    assert "Feeling about reading: unknown" in summary


# --- JSON validation ------------------------------------------------------------------------


def test_valid_turn_is_parsed() -> None:
    turn = parse_dialogue_turn(VALID)
    assert turn.say == "Nice to meet you, Lena!"
    assert turn.expression == "happy" and turn.gesture == "wave"
    assert turn.memory_updates.name == "Lena"


def test_code_fences_and_unknown_values_are_tolerated() -> None:
    raw = '```json\n{"say": "Hi!", "expression": "ecstatic", "gesture": "backflip", "x": 1}\n```'
    turn = parse_dialogue_turn(raw)
    assert (turn.say, turn.expression, turn.gesture) == ("Hi!", "idle", "none")


def test_null_memory_updates_are_tolerated() -> None:
    assert parse_dialogue_turn('{"say": "Hi", "memory_updates": null}').memory_updates.name is None


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("not json at all", "not valid JSON"),
        ("[1, 2]", "expected a JSON object"),
        ('{"expression": "happy"}', "say"),
        ('{"say": "   "}', "say"),
        (json.dumps({"say": "word " * 200}), "say"),
    ],
)
def test_invalid_turns_raise(raw: str, reason: str) -> None:
    with pytest.raises(InvalidModelOutput, match=reason):
        parse_dialogue_turn(raw)


# --- content + prompts ----------------------------------------------------------------------


def test_line_uses_persona_variant_or_default(dialogue_content: DialogueContent) -> None:
    assert dialogue_content.line("opening", "witty") != dialogue_content.line("opening", "calm")
    assert dialogue_content.line("goodbye", "witty") == dialogue_content.lines["goodbye"]["default"]


def test_unknown_line_persona_or_phase_raise_config_error(
    dialogue_content: DialogueContent,
) -> None:
    with pytest.raises(ConfigError):
        dialogue_content.line("nope", "calm")
    with pytest.raises(ConfigError):
        dialogue_content.persona("grumpy")
    with pytest.raises(ConfigError, match="prompts/game_menu.txt"):
        dialogue_content.phase_instruction("GAME_MENU")


def test_broken_content_files_raise_config_error(tmp_path: Path) -> None:
    (tmp_path / "personas.yaml").write_text("personas:\n  calm: {label: Calm}\n", encoding="utf-8")
    (tmp_path / "lines.yaml").write_text("lines:\n  x: {calm: hi}\n", encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    config = DialogueConfig(
        personas_file=tmp_path / "personas.yaml",
        lines_file=tmp_path / "lines.yaml",
        prompts_dir=tmp_path / "prompts",
        reasoning_effort="minimal",
        max_output_tokens=800,
        history_turns=6,
        llm_retries=1,
    )
    with pytest.raises(ConfigError, match="Invalid persona"):
        load_dialogue_content(config)


def _messages(content: DialogueContent, memory: Memory, user_text: str = "I'm Lena") -> list[Any]:
    history = [ConversationTurn("pipi", f"line {i}") for i in range(10)]
    return build_messages(
        persona=content.persona("witty"),
        body="desktop_pet",
        phase="GREETING",
        phase_instruction=content.phase_instruction("GREETING"),
        memory=memory,
        history=history,
        history_turns=6,
        user_text=user_text,
    )


def test_prompt_contains_all_blocks(dialogue_content: DialogueContent) -> None:
    memory, _ = Memory(participant_id="P01", persona="witty").apply(
        MemoryUpdates(name="Lena", interests=["Elden Ring"])
    )
    system, context, user = _messages(dialogue_content, memory)
    assert [m["role"] for m in (system, context, user)] == ["system", "system", "user"]
    assert "You are Pipi" in system["content"]
    assert dialogue_content.persona("witty").tone in system["content"]
    assert "desktop body" in system["content"]
    assert "Current phase: GREETING" in system["content"]
    assert "Return ONLY valid JSON" in system["content"]
    assert "contact details" in system["content"]  # safety rules
    assert "Lena" in context["content"] and "Elden Ring" in context["content"]
    assert user["content"] == "I'm Lena"


def test_context_keeps_only_the_last_n_turns(dialogue_content: DialogueContent) -> None:
    _, context, _ = _messages(dialogue_content, Memory(participant_id="P01", persona="witty"))
    assert "line 9" in context["content"] and "line 4" in context["content"]
    assert "line 3" not in context["content"]


def test_context_without_history() -> None:
    memory = Memory(participant_id="P01", persona="calm")
    assert "(nothing yet)" in build_context(memory=memory, history=[], history_turns=6)
    assert "(nothing yet)" in build_context(
        memory=memory, history=[ConversationTurn("user", "hi")], history_turns=0
    )


# --- LLM engine -----------------------------------------------------------------------------


def _engine(model: FakeChatModel, timeout_s: float = 1.0) -> DialogueEngine:
    return DialogueEngine(model, timeout_s=timeout_s, retries=1)


async def test_valid_answer_on_first_attempt() -> None:
    result = await _engine(FakeChatModel([VALID])).respond([], "fallback")
    assert result.turn.say == "Nice to meet you, Lena!"
    assert (result.fallback_used, result.attempts, result.errors) == (False, 1, ())


async def test_invalid_json_is_retried_once() -> None:
    model = FakeChatModel(["{broken", VALID])
    result = await _engine(model).respond([], "fallback")
    assert not result.fallback_used and result.attempts == 2
    assert len(result.errors) == 1 and "invalid output" in result.errors[0]


async def test_two_failures_give_the_fallback_line() -> None:
    model = FakeChatModel(["nope", RuntimeError("server error 500")])
    result = await _engine(model).respond([], "Hmm, tell me more?")
    assert result.fallback_used and result.attempts == 2
    assert result.turn.say == "Hmm, tell me more?"
    assert result.turn.expression == "idle"
    assert "RuntimeError: server error 500" in result.errors[1]


async def test_timeout_counts_as_a_failed_attempt() -> None:
    model = FakeChatModel([VALID, VALID], delay_s=0.2)
    result = await _engine(model, timeout_s=0.05).respond([], "fallback")
    assert result.fallback_used
    assert all("timeout" in e for e in result.errors)


async def test_error_messages_never_contain_an_api_key() -> None:
    leak = RuntimeError("Incorrect API key provided: sk-proj-abcdEFGH1234")
    result = await _engine(FakeChatModel([leak, leak])).respond([], "fallback")
    assert all("abcdEFGH1234" not in e and "sk-***" in e for e in result.errors)


class _FakeCompletions:
    def __init__(self, content: str | None) -> None:
        self.kwargs: dict[str, Any] = {}
        self._content = content

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def _fake_client(content: str | None) -> Any:
    completions = _FakeCompletions(content)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


async def test_openai_chat_model_sends_reasoning_settings_and_no_temperature() -> None:
    client, completions = _fake_client(VALID)
    model = OpenAIChatModel(
        client, model="gpt-5-nano", reasoning_effort="minimal", max_output_tokens=800
    )
    assert await model.complete_json([{"role": "user", "content": "hi"}]) == VALID
    sent = completions.kwargs
    assert sent["model"] == "gpt-5-nano"
    assert sent["reasoning_effort"] == "minimal"
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["max_completion_tokens"] == 800
    assert "temperature" not in sent


async def test_openai_chat_model_rejects_empty_answer() -> None:
    client, _ = _fake_client(None)
    model = OpenAIChatModel(
        client, model="gpt-5-nano", reasoning_effort="minimal", max_output_tokens=800
    )
    with pytest.raises(LlmError, match="empty answer"):
        await model.complete_json([])


async def test_engine_is_cancellable() -> None:
    task = asyncio.create_task(_engine(FakeChatModel([VALID], delay_s=5)).respond([], "fb"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
