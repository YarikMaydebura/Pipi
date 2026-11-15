"""Measure gpt-5-nano: does it accept images, and how fast is each reasoning effort?

Run by hand only (it uses the real API key and costs a few cents):

    python -m pipi_brain.tools.check_nano --config ../config/dev.yaml [--runs 3]

It sends (1) a normal Pipi dialogue turn several times per reasoning effort and prints the
median latency, and (2) one tiny generated red PNG asking for its colour. Copy the results
into docs/ROBOT_RIDK.md section 4 ("Measured facts"). The model name comes from config.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import statistics
import struct
import sys
import time
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipi_brain.config import ConfigError, LoadedConfig, ReasoningEffort, load_config
from pipi_brain.dialogue.content import load_dialogue_content
from pipi_brain.dialogue.llm import OpenAIChatModel
from pipi_brain.dialogue.prompts import build_messages
from pipi_brain.dialogue.schemas import InvalidModelOutput, parse_dialogue_turn
from pipi_brain.memory import Memory
from pipi_brain.openai_client import create_openai_client
from pipi_brain.resilience import describe_error

EFFORTS: tuple[ReasoningEffort, ...] = ("minimal", "low")
CALL_TIMEOUT_S = 30.0


def red_png(size: int = 32) -> bytes:
    """A solid red PNG built with the standard library only."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + b"\xff\x00\x00" * size
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


async def _measure_effort(
    client: Any, loaded: LoadedConfig, effort: ReasoningEffort, runs: int
) -> str:
    app = loaded.app
    content = load_dialogue_content(app.dialogue)
    model = OpenAIChatModel(
        client,
        model=app.models.dialogue,
        reasoning_effort=effort,
        max_output_tokens=app.dialogue.max_output_tokens,
    )
    messages = build_messages(
        persona=content.persona(app.persona.default),
        body="desktop_pet",
        phase="GREETING",
        phase_instruction=content.phase_instruction("GREETING"),
        memory=Memory(participant_id="DEV", persona=app.persona.default),
        history=[],
        history_turns=app.dialogue.history_turns,
        user_text="Hi, I'm Sam and I like playing football.",
    )
    times: list[int] = []
    valid = 0
    for _ in range(runs):
        start = time.perf_counter()
        try:
            raw = await asyncio.wait_for(model.complete_json(messages), CALL_TIMEOUT_S)
            parse_dialogue_turn(raw)
            valid += 1
        except InvalidModelOutput as exc:
            print(f"    invalid JSON: {exc}")
        except Exception as exc:  # report and keep measuring the other runs
            print(f"    error: {describe_error(exc)}")
            continue
        times.append(round((time.perf_counter() - start) * 1000))
    if not times:
        return f"{effort:<8} all {runs} calls failed"
    return (
        f"{effort:<8} median {statistics.median(times):.0f} ms  "
        f"(min {min(times)}, max {max(times)}; valid JSON {valid}/{runs})"
    )


async def _check_image(client: Any, loaded: LoadedConfig) -> str:
    image_url = "data:image/png;base64," + base64.b64encode(red_png()).decode("ascii")
    start = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=loaded.app.models.dialogue,
                reasoning_effort="minimal",
                max_completion_tokens=200,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What colour is this image? One word."},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
            ),
            CALL_TIMEOUT_S,
        )
    except Exception as exc:  # the point of this check is to see whether it fails
        return f"NO - request failed: {describe_error(exc)}"
    elapsed = round((time.perf_counter() - start) * 1000)
    answer = (response.choices[0].message.content or "").strip()
    verdict = "YES" if "red" in answer.lower() else "UNCLEAR"
    return f"{verdict} - answered {answer!r} in {elapsed} ms"


async def _run(loaded: LoadedConfig, runs: int) -> None:
    api_key = loaded.secrets.openai_api_key
    if api_key is None:
        raise ConfigError("OPENAI_API_KEY is missing")
    client = create_openai_client(api_key)
    print(f"Model: {loaded.app.models.dialogue}  ({runs} runs per effort)")
    print("Latency of one Pipi dialogue turn:")
    for effort in EFFORTS:
        print(f"  {await _measure_effort(client, loaded, effort, runs)}")
    print(f"Accepts image input: {await _check_image(client, loaded)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipi_brain.tools.check_nano", description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3, choices=range(1, 11), metavar="1-10")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(load_config(args.config), args.runs))
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
