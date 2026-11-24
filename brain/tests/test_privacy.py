"""The name safety net: when the LLM cannot pick the name out, a simple rule finds it for the
log redaction only (Pipi's memory is never filled from it)."""

from __future__ import annotations

import pytest

from pipi_brain.privacy import guess_name


@pytest.mark.parametrize(
    ("answer", "name"),
    [
        ("Lena", "Lena"),
        ("lena.", "lena"),
        ("I'm Lena", "Lena"),
        ("im lena", "lena"),
        ("Hi, I am Lena!", "Lena"),
        ("My name is Lena", "Lena"),
        ("my name's Lena and I like games", "Lena"),
        ("Call me Lena", "Lena"),
        ("It's Lena", "Lena"),
        ("Hi Lena", "Lena"),
        ("Hello! Jiyuan", "Jiyuan"),
        ("I'm José", "José"),
    ],
)
def test_the_name_is_found_in_a_typical_answer(answer: str, name: str) -> None:
    assert guess_name(answer, first_answer=True) == name


@pytest.mark.parametrize(
    "answer",
    ["", "yes", "Hi!", "I don't know", "what?", "I'm tired", "I'm fine, thanks", "ok sure"],
)
def test_no_name_is_guessed_from_answers_without_one(answer: str) -> None:
    assert guess_name(answer, first_answer=True) is None


def test_a_later_answer_needs_an_explicit_phrase() -> None:
    # A one-word answer is only a name right after "What's your name?".
    assert guess_name("football", first_answer=False) is None
    assert guess_name("Oh, my name is Lena by the way", first_answer=False) == "Lena"
