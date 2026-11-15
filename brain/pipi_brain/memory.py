"""Session memory shared by every body (docs/PERSONA_AND_PROMPTS.md section 6).

``Memory`` is immutable: :meth:`Memory.apply` returns a NEW memory plus the list of fields that
changed. ``MemoryUpdates`` is what the LLM sends back in ``memory_updates``; it is lenient
(empty strings are ignored, long strings are cut) because a slightly odd value is better than
throwing the whole turn away.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

MAX_NAME_CHARS = 40
MAX_LABEL_CHARS = 60
MAX_TEXT_CHARS = 200
MAX_INTERESTS = 5
MAX_QUOTES = 10


def _clean(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] if text else None


class MemoryUpdates(BaseModel):
    """Facts the LLM extracted from the latest utterance. Every field is optional."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str | None = None
    interests: tuple[str, ...] = ()
    reading_feeling: str | None = None
    quote: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: Any) -> str | None:
        return _clean(value, MAX_NAME_CHARS)

    @field_validator("reading_feeling", "quote", mode="before")
    @classmethod
    def _clean_text(cls, value: Any) -> str | None:
        return _clean(value, MAX_TEXT_CHARS)

    @field_validator("interests", mode="before")
    @classmethod
    def _clean_interests(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        items = [value] if isinstance(value, str) else list(value)
        cleaned = (_clean(item, MAX_LABEL_CHARS) for item in items)
        return tuple(item for item in cleaned if item)[:MAX_INTERESTS]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Interest(_Frozen):
    label: str
    quote: str | None = None


class WordHelp(_Frozen):
    term: str
    phase: str
    ts: int


class GameEvent(_Frozen):
    game: str
    summary: str


class Memory(_Frozen):
    participant_id: str
    persona: str
    name: str | None = None
    interests: tuple[Interest, ...] = ()
    reading_feeling: str | None = None
    word_help: tuple[WordHelp, ...] = ()
    game_events: tuple[GameEvent, ...] = ()
    notable_quotes: tuple[str, ...] = ()
    break_highlight: str | None = None

    def apply(self, updates: MemoryUpdates) -> tuple[Memory, list[str]]:
        """Return (new memory, names of the fields that changed). ``self`` is not modified."""
        changes: dict[str, Any] = {}
        if updates.name and updates.name != self.name:
            changes["name"] = updates.name
        if updates.reading_feeling and updates.reading_feeling != self.reading_feeling:
            changes["reading_feeling"] = updates.reading_feeling

        known = {interest.label.casefold() for interest in self.interests}
        new_interests = tuple(
            Interest(label=label, quote=updates.quote)
            for label in dict.fromkeys(updates.interests)  # de-duplicate, keep order
            if label.casefold() not in known
        )
        if new_interests:
            changes["interests"] = (self.interests + new_interests)[:MAX_INTERESTS]
        elif updates.quote and updates.quote not in self.notable_quotes:
            changes["notable_quotes"] = (self.notable_quotes + (updates.quote,))[-MAX_QUOTES:]

        if not changes:
            return self, []
        return self.model_copy(update=changes), list(changes)

    @property
    def greeting_complete(self) -> bool:
        """True once GREETING learned everything it asks for (name, interest, feeling)."""
        return bool(self.name and self.interests and self.reading_feeling)

    def summary_for_prompt(self) -> str:
        """Plain-text memory block for the LLM context."""
        lines = [f"Participant's name: {self.name or 'unknown (not asked yet)'}"]
        if self.interests:
            parts = [f'{i.label} ("{i.quote}")' if i.quote else i.label for i in self.interests]
            lines.append(f"Interests: {'; '.join(parts)}")
        else:
            lines.append("Interests: unknown (not asked yet)")
        lines.append(f"Feeling about reading: {self.reading_feeling or 'unknown (not asked yet)'}")
        if self.notable_quotes:
            lines.append(f"Things they said: {' | '.join(self.notable_quotes)}")
        if self.game_events:
            lines.append(
                "Break moments: " + "; ".join(f"{e.game}: {e.summary}" for e in self.game_events)
            )
        return "\n".join(lines)
