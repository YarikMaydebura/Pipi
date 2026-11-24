"""A whole session, SETUP -> END, with fake bodies, fake speech/LLM and virtual time."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pipi_brain.bodies.base import BodyResult, Entrance
from pipi_brain.config import LoadedConfig
from pipi_brain.dialogue.content import DialogueContent
from pipi_brain.fakes import FakeBody
from pipi_brain.speech.base import Utterance

from .session_harness import Session, make_session, turn

FULL_FLOW = [
    "PERSONA_PICK",
    "GREETING",
    "FOCUS",
    "MIGRATE_OUT",
    "ROBOT_WAKE",
    "CHAT",
    "GAME_CROCODILE",
    "GAME_MENU",
    "GAME_CHOSEN",
    "ROBOT_GOODBYE",
    "MIGRATE_IN",
    "RETURN",
    "END",
]

GREETING_LLM = [
    turn("Nice to meet you, Lena! What do you do for fun?", memory_updates={"name": "Lena"}),
    turn("Cool! How do you feel about reading?", memory_updates={"interests": ["Elden Ring"]}),
    turn("Got it.", memory_updates={"reading_feeling": "a bit tired"}),
]
HAPPY_SCRIPT: list[object] = ["witty", "I'm Lena", "I play Elden Ring", "a bit tired"]


def happy(
    loaded: LoadedConfig,
    content: DialogueContent,
    tmp_path: Path,
    *,
    extra_script: list[object] | None = None,
    extra_llm: list[object] | None = None,
    **kw: Any,
) -> Session:
    return make_session(
        loaded,
        content,
        tmp_path,
        script=[*HAPPY_SCRIPT, *(extra_script or [])],
        llm=[*GREETING_LLM, *(extra_llm or [])],
        **kw,
    )


def utterance() -> Utterance:
    return Utterance(np.zeros(1600, dtype=np.float32), 16000, 0.0, 0.1, False)


class SharedLogBody(FakeBody):
    """Records calls as (body, call, arg) into one list shared by all bodies (global order)."""

    def __init__(self, name: str, shared: list[tuple[str, str, object]], **kw: Any) -> None:
        super().__init__(name=name, **kw)
        self._shared = shared

    def _result(self, name: str, arg: object) -> BodyResult:
        self._shared.append((self.name, name, arg))
        return super()._result(name, arg)

    async def speak(self, text: str, audio: Any, expression: Any = "idle") -> Any:
        self._shared.append((self.name, "speak", text))
        return await super().speak(text, audio, expression)


class NoWakeBody(FakeBody):
    async def activate(self, entrance: Entrance) -> BodyResult:
        self.calls.append(("activate", entrance))
        return BodyResult(ok=False, error="no ack within 8 s", timed_out=True)


async def test_full_session_runs_every_phase_and_writes_the_log(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(dev_config, dialogue_content, tmp_path)
    summary = await s.run()
    assert s.phases() == FULL_FLOW
    assert summary["end_reason"] == "completed"
    assert s.ctl.state.memory.name == "Lena"
    assert s.ctl.state.persona == "witty"
    types = [e["type"] for e in s.events()]
    assert types[0] == "session_start" and types[-1] == "session_end"
    folder = s.logger.folder
    assert json.loads((folder / "memory.json").read_text("utf-8"))["name"] == "Lena"
    saved = json.loads((folder / "summary.json").read_text("utf-8"))
    assert saved["phase_durations_ms"]["FOCUS"] == 30_000  # virtual time: exact
    # privacy: the name is in memory.json, but nowhere in events.jsonl (also not in what the
    # participant said before Pipi knew it was a name, nor in Pipi's replies)
    assert all("Lena" not in json.dumps(d) for d in s.data("memory_update"))
    assert "lena" not in (folder / "events.jsonl").read_text("utf-8").lower()
    user_turns = [d["text"] for d in s.data("turn") if d["speaker"] == "user"]
    assert "I'm [NAME]" in user_turns
    start = s.data("session_start")[0]
    assert start["cue_checklist"]["signature_phrase"] is True


async def test_migration_choreography_is_exact(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    shared: list[tuple[str, str, object]] = []
    bodies = {
        "desktop_pet": SharedLogBody("desktop_pet", shared),
        "fake_robot": SharedLogBody("fake_robot", shared),
    }
    s = happy(dev_config, dialogue_content, tmp_path, bodies=bodies)
    await s.run()
    moves = [c for c in shared if c[1] in ("activate", "deactivate", "motion", "speak")]
    announce = next(
        i for i, c in enumerate(moves) if c[2] == "Break time! Watch me jump into my robot body."
    )
    assert moves[announce - 1] == ("desktop_pet", "motion", "signature_wave")
    assert moves[announce + 1] == ("desktop_pet", "deactivate", "jump_out")
    assert moves[announce + 2] == ("fake_robot", "activate", "wake_up")
    assert moves[announce + 3] == ("fake_robot", "motion", "signature_wave")
    assert moves[announce + 4] == ("fake_robot", "speak", "Ta-da! Hi again, Lena!")
    sleep = moves.index(("fake_robot", "deactivate", "sleep"))
    assert moves[sleep + 1] == ("desktop_pet", "activate", "jump_in")
    out_end = [d for d in s.data("migration") if d["stage"] == "end" and d["direction"] == "out"]
    steps = [step["step"] for step in out_end[0]["steps"]]
    assert steps == ["announce", "pet_exit", "flight", "robot_wake"]
    assert out_end[0]["success"] is True
    assert {"what": ["name"], "body": "fake_robot"} in s.data("memory_reference")
    # the 0.8 s flight: MIGRATE_OUT lasts exactly the flight in virtual time
    assert s.ctl.state.phase_durations_s["MIGRATE_OUT"] == pytest.approx(0.8)


async def test_calm_mode_is_on_for_the_whole_focus_phase(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(dev_config, dialogue_content, tmp_path)
    await s.run()
    calls = s.pet.calls
    on, off = calls.index(("calm", True)), calls.index(("calm", False))
    focus_line = calls.index(
        ("speak", "Reading time! I'll be right here, ask me if a word looks suspicious.")
    )
    assert on < focus_line < calls.index(("motion", "yawn")) < off
    assert off < calls.index(("deactivate", "jump_out"))
    assert s.data("focus_precue")[0]["remaining_s"] == 10.0


async def test_word_help_during_focus(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    answer = turn("It means making food from light.", help_term="photosynthesis")
    s = happy(
        dev_config,
        dialogue_content,
        tmp_path,
        extra_script=[("what is photosynthesis?", 5)],
        extra_llm=[answer],
    )
    await s.run()
    assert s.data("word_help") == [
        {"term": "photosynthesis", "answer": "It means making food from light."}
    ]
    assert s.ctl.state.memory.word_help[0].term == "photosynthesis"
    focus_prompt = s.chat.calls[3][0]["content"]
    assert "Current phase: FOCUS" in focus_prompt and "help_term" in focus_prompt


async def test_robot_missing_keeps_pipi_on_the_pet(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(dev_config, dialogue_content, tmp_path, robot_connected=False)
    summary = await s.run()
    assert summary["end_reason"] == "completed"
    assert "ROBOT_WAKE" not in s.phases()
    assert ("deactivate", "jump_out") not in s.pet.calls  # never jumped off
    assert s.robot.calls == []
    end = [d for d in s.data("migration") if d.get("stage") == "end"][0]
    assert end["success"] is False and end["fallback"] == "stay_on_pet"
    assert any(a["level"] == "error" for a in s.data("alert"))
    assert "migration_unavailable" in s.pipi_lines()
    chat_turns = [e for e in s.events("turn") if e["phase"] == "CHAT"]
    assert chat_turns and all(e["body"] == "desktop_pet" for e in chat_turns)
    skipped = [d for d in s.data("migration") if d.get("stage") == "skipped"]
    assert skipped[0]["direction"] == "in"


async def test_robot_that_does_not_wake_sends_pipi_back_to_the_screen(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    pet = FakeBody(name="desktop_pet")
    s = happy(
        dev_config,
        dialogue_content,
        tmp_path,
        bodies={"desktop_pet": pet, "fake_robot": NoWakeBody(name="fake_robot")},
    )
    await s.run()
    jump_out = pet.calls.index(("deactivate", "jump_out"))
    assert pet.calls[jump_out + 1] == ("activate", "jump_in")
    end = [d for d in s.data("migration") if d.get("stage") == "end"][0]
    assert [step["step"] for step in end["steps"]][-1] == "pet_back"
    assert s.ctl.bodies.active_name == "desktop_pet"


async def test_break_max_forces_a_polite_goodbye(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(
        dev_config,
        dialogue_content,
        tmp_path,
        timers={"break_max_s": 20},
        session={"chat_max_s": 120},
    )
    await s.run()
    changes = s.data("phase_change")
    forced = [c for c in changes if c["to"] == "ROBOT_GOODBYE"][0]
    assert forced["from"] == "CHAT" and forced["trigger"] == "timer"
    assert any("break_max_s" in a["message"] for a in s.data("alert"))
    assert "GAME_CROCODILE" not in s.phases()


async def test_silence_gets_one_reprompt_then_the_default(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(dev_config, dialogue_content, tmp_path)
    await s.run()
    chat = [e["data"] for e in s.events("silence_reprompt") if e["phase"] == "CHAT"]
    assert [d["action"] for d in chat] == ["reprompt", "default"]
    assert chat[0]["waited_s"] == 12


async def test_persona_timeout_uses_the_default(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = make_session(dev_config, dialogue_content, tmp_path, script=[None])
    await s.run()
    assert s.data("persona_choice") == [{"persona": "cheerful", "method": "timeout"}]
    assert "persona_default" in s.pipi_lines()
    assert s.data("phase_change")[1]["trigger"] == "timer"


PERSONA_IDS = ["cheerful", "calm", "witty"]


def _pickers(s: Session) -> list[list[str]]:
    """Every persona_picker the pet got, as lists of persona ids ([] = hide)."""
    return [
        [option.id for option in options]  # type: ignore[attr-defined]
        for call, options in s.pet.calls
        if call == "persona_picker"
    ]


async def test_a_click_on_a_persona_card_chooses_the_persona(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = make_session(dev_config, dialogue_content, tmp_path, script=[None, *HAPPY_SCRIPT[1:]])
    s.pet.persona_click = "persona:calm"  # the participant clicks instead of talking

    await s.run()

    assert s.data("persona_choice") == [{"persona": "calm", "method": "click"}]
    assert s.ctl.state.persona == "calm"
    assert _pickers(s) == [PERSONA_IDS, []]  # cards shown, then hidden
    assert "persona_chosen" in s.pipi_lines()


async def test_voice_still_works_and_the_cards_are_hidden_afterwards(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(dev_config, dialogue_content, tmp_path)

    await s.run()

    assert s.data("persona_choice") == [{"persona": "witty", "method": "voice"}]
    assert _pickers(s) == [PERSONA_IDS, []]


async def test_clicks_that_are_not_a_known_persona_card_are_ignored(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    # A click on Pipi itself ("pipi") or an unknown card must not pick anything.
    s = make_session(dev_config, dialogue_content, tmp_path, script=[None])
    s.pet.persona_click = "persona:grumpy"

    await s.run()

    assert s.data("persona_choice") == [{"persona": "cheerful", "method": "timeout"}]
    assert _pickers(s)[-1] == []


async def test_persona_unclear_answer_gets_one_clarifying_question(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = make_session(
        dev_config, dialogue_content, tmp_path, script=["hmm, no idea", "the calm one"]
    )
    await s.run()
    assert s.data("persona_choice")[0] == {"persona": "calm", "method": "voice"}
    assert "persona_unclear" in s.pipi_lines()


async def test_fixed_persona_skips_the_question(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = make_session(
        dev_config, dialogue_content, tmp_path, persona={"allow_choice": False, "default": "calm"}
    )
    await s.run()
    assert s.data("persona_choice") == [{"persona": "calm", "method": "config_fixed"}]
    assert "persona_intro" not in s.pipi_lines()


async def test_empty_transcript_gets_one_clarification(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = make_session(dev_config, dialogue_content, tmp_path, script=[utterance(), utterance()])
    s.stt.answers = ["", "witty please"]
    await s.run()
    assert s.data("clarification")[0] == {"reason": "empty_transcript"}
    retry = [d for d in s.data("turn") if d.get("line_id") == "stt_retry"][0]
    assert retry["fallback_used"] == "empty" and retry["total_ms"] is not None
    user = [d for d in s.data("turn") if d["speaker"] == "user"][0]
    assert user["input"] == "voice" and user["stt_ms"] is not None
    assert s.data("persona_choice")[0]["persona"] == "witty"


async def test_stt_failure_is_logged_and_retried(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = make_session(dev_config, dialogue_content, tmp_path, script=[utterance(), utterance()])
    s.stt.answers = [RuntimeError("network down"), RuntimeError("still down")]
    await s.run()
    assert len(s.data("stt_error")) == 2
    assert s.data("persona_choice")[0]["method"] == "timeout"  # gave up -> default later


async def test_slow_reply_shows_thinking_eyes(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(dev_config, dialogue_content, tmp_path)
    s.chat.delay_s = 0.02  # real time; virtual time jumps past 300 ms meanwhile
    await s.run()
    assert ("eyes", "thinking") in s.pet.calls


async def test_missing_pet_falls_back_to_the_laptop_speaker(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(dev_config, dialogue_content, tmp_path, pet_connected=False)
    await s.run()
    fallbacks = s.data("body_fallback")
    assert fallbacks and fallbacks[0]["fallback"] == "local_speaker"
    assert s.speaker.played
    assert any("Desktop pet not connected" in a["message"] for a in s.data("alert"))


async def test_llm_and_tts_failures_use_fallbacks(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = make_session(
        dev_config,
        dialogue_content,
        tmp_path,
        script=["calm", "Lena"],
        llm=[RuntimeError("boom"), "not json"],
    )
    s.tts.failures = [RuntimeError("tts down")]
    await s.run()
    assert [d["attempt"] for d in s.data("llm_error")][:2] == [1, 2]
    assert "llm_fallback" in s.pipi_lines()
    assert s.data("tts_error")[0]["fallback"] == "captions_only"
    assert s.data("turn")[0]["audio"] is False


async def test_the_name_is_redacted_even_when_the_llm_never_learned_it(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    # LLM down during GREETING: Pipi does not know the name, but the participant said it.
    s = make_session(
        dev_config,
        dialogue_content,
        tmp_path,
        script=["calm", "I'm Lena"],
        llm=[RuntimeError("boom"), RuntimeError("boom")],
    )
    await s.run()
    assert s.ctl.state.memory.name is None  # memory is never filled by the safety net
    assert "lena" not in (s.logger.folder / "events.jsonl").read_text("utf-8").lower()


async def test_every_m3_event_type_is_logged(
    dev_config: LoadedConfig, dialogue_content: DialogueContent, tmp_path: Path
) -> None:
    s = happy(
        dev_config,
        dialogue_content,
        tmp_path / "a",
        extra_script=[("what does 'lucid' mean?", 2)],
        extra_llm=[turn("Clear and easy.", help_term="lucid")],
        pet_connected=True,
    )
    s.tts.failures = [RuntimeError("tts down")]
    task = s.start()
    await s.until_phase("FOCUS")
    await s.woz("set_eyes", state="happy")
    await task
    types = {e["type"] for e in s.events()}
    s2 = make_session(
        dev_config,
        dialogue_content,
        tmp_path / "b",
        script=[utterance(), "hmm"],
        llm=["{"] * 4,
        pet_connected=False,
    )
    s2.stt.answers = [RuntimeError("down")]
    await s2.run()
    types |= {e["type"] for e in s2.events()}
    expected = {
        "session_start",
        "health_check",
        "phase_change",
        "turn",
        "persona_choice",
        "memory_update",
        "migration",
        "memory_reference",
        "silence_reprompt",
        "clarification",
        "word_help",
        "game_start",
        "game_end",
        "game_choice",
        "woz_action",
        "alert",
        "session_end",
        "llm_error",
        "stt_error",
        "tts_error",
        "body_fallback",
        "focus_precue",
    }
    assert expected <= types, expected - types
