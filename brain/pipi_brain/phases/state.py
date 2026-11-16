"""What the session knows right now. One mutable holder; the values in it are immutable
(``Memory`` is replaced, never changed in place), so it is always clear who changed what."""

from __future__ import annotations

from dataclasses import dataclass, field

from pipi_brain.dialogue.prompts import ConversationTurn
from pipi_brain.latency import TurnLatency
from pipi_brain.memory import Memory
from pipi_brain.phases.timers import Countdown
from pipi_brain.protocol import Phase


@dataclass
class SessionState:
    memory: Memory
    phase: Phase = "SETUP"
    history: tuple[ConversationTurn, ...] = ()  # turns of the current phase (LLM context)
    phase_timer: Countdown | None = None  # shown in the WoZ panel (focus, chat, ...)
    break_timer: Countdown | None = None  # break_max_s, from MIGRATE_OUT to MIGRATE_IN
    chosen_game: str | None = None
    last_game: str | None = None  # the game played last ("again" in the menu means this one)
    goodbye_said: str | None = None  # the robot's goodbye, so RETURN recalls something else
    focus_extra_s: float = 0.0  # extend_focus that arrived before the timer started
    after_migration: Phase | None = None  # WoZ jumped across bodies: where to go afterwards
    break_on_pet: bool = False  # robot unavailable: the break happens on the screen
    halted: bool = False  # emergency stop: nothing runs until resume / goto / end
    user_turns: int = 0
    latencies: tuple[TurnLatency, ...] = ()
    phase_durations_s: dict[str, float] = field(default_factory=dict)

    @property
    def persona(self) -> str:
        return self.memory.persona

    def add_turn(self, speaker: str, text: str) -> None:
        self.history = (*self.history, ConversationTurn(speaker, text))  # type: ignore[arg-type]
