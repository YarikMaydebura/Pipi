"""Validates shared/fixtures/protocol_examples.json, the same file shared/protocol.test.ts uses.

If a message is changed in protocol.py but not in protocol.ts (or vice versa), one of the two
test suites fails.
"""

from __future__ import annotations

import json
import typing
from typing import Any

import pytest
from pydantic import ValidationError

from pipi_brain.protocol import (
    BODY_TO_BRAIN,
    BRAIN_TO_BODY,
    BRAIN_TO_WOZ,
    BodyToBrain,
    BrainToBody,
    BrainToWoz,
    Hello,
    Speak,
    WozCommand,
    encode,
    parse_body_message,
    parse_woz_message,
)

from .conftest import PROTOCOL_FIXTURE

EXAMPLES: dict[str, list[dict[str, Any]]] = json.loads(PROTOCOL_FIXTURE.read_text(encoding="utf-8"))


def _ids(examples: list[dict[str, Any]]) -> list[str]:
    return [str(e.get("type")) for e in examples]


def _message_types(union: Any) -> set[str]:
    members = typing.get_args(typing.get_args(union)[0])
    return {m.model_fields["type"].default for m in members}


@pytest.mark.parametrize("example", EXAMPLES["brain_to_body"], ids=_ids(EXAMPLES["brain_to_body"]))
def test_brain_to_body_examples_parse_and_round_trip(example: dict[str, Any]) -> None:
    message = BRAIN_TO_BODY.validate_python(example)
    assert message.model_dump(mode="json", exclude_unset=True) == example


@pytest.mark.parametrize("example", EXAMPLES["body_to_brain"], ids=_ids(EXAMPLES["body_to_brain"]))
def test_body_to_brain_examples_parse_and_round_trip(example: dict[str, Any]) -> None:
    message = parse_body_message(json.dumps(example))
    assert message.model_dump(mode="json", exclude_unset=True) == example


@pytest.mark.parametrize(
    "example", EXAMPLES["invalid_brain_to_body"], ids=_ids(EXAMPLES["invalid_brain_to_body"])
)
def test_invalid_brain_to_body_examples_are_rejected(example: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BRAIN_TO_BODY.validate_json(json.dumps(example))


@pytest.mark.parametrize(
    "example", EXAMPLES["invalid_body_to_brain"], ids=_ids(EXAMPLES["invalid_body_to_brain"])
)
def test_invalid_body_to_brain_examples_are_rejected(example: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BODY_TO_BRAIN.validate_json(json.dumps(example))


@pytest.mark.parametrize("example", EXAMPLES["woz_to_brain"], ids=_ids(EXAMPLES["woz_to_brain"]))
def test_woz_to_brain_examples_parse_and_round_trip(example: dict[str, Any]) -> None:
    message = parse_woz_message(json.dumps(example))
    assert message.model_dump(mode="json", exclude_unset=True) == example


@pytest.mark.parametrize("example", EXAMPLES["brain_to_woz"], ids=_ids(EXAMPLES["brain_to_woz"]))
def test_brain_to_woz_examples_parse_and_round_trip(example: dict[str, Any]) -> None:
    message = BRAIN_TO_WOZ.validate_json(json.dumps(example))
    assert message.model_dump(mode="json", exclude_unset=True) == example


@pytest.mark.parametrize(
    "example", EXAMPLES["invalid_woz_to_brain"], ids=_ids(EXAMPLES["invalid_woz_to_brain"])
)
def test_invalid_woz_to_brain_examples_are_rejected(example: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse_woz_message(json.dumps(example))


@pytest.mark.parametrize(
    "example", EXAMPLES["invalid_brain_to_woz"], ids=_ids(EXAMPLES["invalid_brain_to_woz"])
)
def test_invalid_brain_to_woz_examples_are_rejected(example: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        BRAIN_TO_WOZ.validate_json(json.dumps(example))


def test_woz_command_args_default_to_empty() -> None:
    command = WozCommand(command="pause", reason="timing")
    assert command.args == {} and command.note is None


def test_fixture_covers_every_message_type() -> None:
    assert {e["type"] for e in EXAMPLES["brain_to_body"]} == _message_types(BrainToBody)
    assert {e["type"] for e in EXAMPLES["body_to_brain"]} == _message_types(BodyToBrain)
    assert {e["type"] for e in EXAMPLES["brain_to_woz"]} == _message_types(BrainToWoz)
    assert {e["type"] for e in EXAMPLES["woz_to_brain"]} == {"woz_command"}


def test_new_message_gets_id_and_timestamp() -> None:
    a = Hello(body="desktop_pet", version="0.1.0")
    b = Hello(body="desktop_pet", version="0.1.0")
    assert a.id != b.id
    assert a.ts > 0


def test_speak_defaults_to_idle_expression_and_no_audio() -> None:
    speak = Speak(text="hi")
    assert speak.expression == "idle"
    assert speak.audio_b64 is None


def test_encode_produces_json_the_parser_accepts() -> None:
    hello = Hello(body="fake_robot", version="0.1.0")
    assert parse_body_message(encode(hello)) == hello
