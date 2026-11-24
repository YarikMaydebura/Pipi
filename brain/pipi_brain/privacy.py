"""Privacy helpers: find the participant's first name in an answer, for log redaction only.

Normally the LLM picks the name out of the answer to "What's your name?" and the study logger
then writes it as ``[NAME]`` (``StudyLogger.redact_name``). When the LLM fails (network down,
offline session) the name is never learned, but the participant has said it. This simple rule
finds it so the log can still be redacted. Its result is NEVER put into Pipi's memory: a wrong
guess must only ever cost a redacted word, not a wrong name in Pipi's mouth.
"""

from __future__ import annotations

import re

_WORD = r"([^\W\d_](?:[^\W\d_]|['-]){1,30})"  # letters (any language); may contain ' or -
_PHRASE = re.compile(
    r"(?:\bmy name(?:'s| is)|\bi'?m|\bi am|\bcall me|\bit'?s|\bit is|\bthis is)\s+" + _WORD,
    re.IGNORECASE,
)
# Words that are not names, also when they follow "I'm" ("I'm fine") or stand alone ("yes").
_NOT_NAMES = frozenset(
    (  # noqa: SIM905  (a one-word-per-line list would be 60 lines)
        "hi hello hey yes yeah no nope ok okay sure um uh hmm well so oh thanks thank you "
        "fine good great tired sorry not what why who me i it is am a the just really very "
        "pretty quite here ready back bored happy sad sleepy busy done going doing feeling "
        "know don't dont i'm im it's its that's i'll"
    ).split()
)


def guess_name(answer: str, *, first_answer: bool) -> str | None:
    """The likely first name in ``answer``, or None.

    Any answer: "I'm X", "I am X", "my name is X", "call me X", "it's X", "this is X".
    Only the first answer after the name question: a reply that is a single word once
    greetings and fillers are removed ("Lena", "Hi Lena", "Lena.").
    """
    for match in _PHRASE.finditer(answer):
        word = match.group(1)
        if word.lower() not in _NOT_NAMES:
            return word
    if not first_answer:
        return None
    words = [w for w in re.findall(_WORD, answer) if w.lower() not in _NOT_NAMES]
    plain = re.sub(r"[\s!?.,;:]+", " ", answer).strip().split(" ")
    if len(words) == 1 and len(plain) <= 3:  # "Lena", "Hi Lena", "Hello! Jiyuan"
        return words[0]
    return None
