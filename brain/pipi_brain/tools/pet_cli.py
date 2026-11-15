"""Drive the desktop pet or the fake robot by hand (dev tool).

Run: ``python -m pipi_brain.tools.pet_cli --config ../config/dev.yaml [--body robot]``

Starts the body WebSocket server (both bodies may connect), waits for the chosen body (pet:
``npm run dev`` in desktop-pet/; robot: http://localhost:5173/fake-robot/ from ``npm run dev``
in web/) and reads commands from the terminal. ``say`` uses a synthetic babble voice (no API
call) unless ``--tts`` is given, which uses the real tts-1 voice from config (a
little quota).
Every message and failure is logged like in a session (logs/PETCLI_<time>/events.jsonl).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, get_args

from pipi_brain.bodies.base import Body, BodyResult, Entrance, Exit
from pipi_brain.config import ConfigError, LoadedConfig, load_config
from pipi_brain.logging_study import LoggerError, StudyLogger
from pipi_brain.protocol import EyeState
from pipi_brain.resilience import timed_call
from pipi_brain.server import BodyServer, BodyServerError
from pipi_brain.speech.base import SpeechAudio
from pipi_brain.tools.babble import babble

EYE_STATES: tuple[str, ...] = get_args(EyeState)
ENTRANCES: tuple[str, ...] = get_args(Entrance)
EXITS: tuple[str, ...] = get_args(Exit)
QUIT = frozenset({"quit", "exit", "/quit", "q"})

HELP = f"""Commands:
  eyes <state>        {" ".join(EYE_STATES)}
  motion <name>       e.g. nod, wave, signature_wave, hop, excited, think, celebrate
  say <text>          speak with audio (babble voice, or tts-1 with --tts)
  text <text>         speak without audio (caption only)
  caption [<text>]    show a caption; without text: hide it
  out [exit]          jump off the screen: {" | ".join(EXITS)} (default jump_out)
  in [entrance]       come back: {" | ".join(ENTRANCES)} (default jump_in)
  status              is the body connected?
  help                this text
  quit                stop"""

Synthesize = Callable[[str], Awaitable[SpeechAudio]]


async def babble_voice(text: str) -> SpeechAudio:
    return babble(text)


def _format(result: BodyResult) -> str:
    if result.ok:
        return f"ok ({result.elapsed_ms} ms)"
    return f"failed: {result.error}"


@dataclass
class PetCli:
    body: Body
    synthesize: Synthesize = babble_voice

    async def execute(self, line: str) -> str | None:
        """Run one command line; returns the text to print, or None to quit."""
        command, _, rest = line.strip().partition(" ")
        command, rest = command.lower(), rest.strip()
        if not command:
            return ""
        if command in QUIT:
            return None
        handler = self._handlers().get(command)
        if handler is None:
            return f"unknown command '{command}' (type help)"
        return await handler(rest)

    def _handlers(self) -> Mapping[str, Callable[[str], Awaitable[str]]]:
        return {
            "eyes": self._eyes,
            "motion": self._motion,
            "say": self._say,
            "text": self._text,
            "caption": self._caption,
            "out": self._out,
            "in": self._in,
            "status": self._status,
            "help": self._help,
        }

    async def _eyes(self, arg: str) -> str:
        if arg not in EYE_STATES:
            return f"eye state must be one of: {' '.join(EYE_STATES)}"
        return _format(await self.body.set_eyes(arg))  # type: ignore[arg-type]

    async def _motion(self, arg: str) -> str:
        if not arg:
            return "usage: motion <name>"
        return _format(await self.body.play_motion(arg))

    async def _say(self, arg: str) -> str:
        if not arg:
            return "usage: say <text>"
        audio = await self.synthesize(arg)
        return await self._speak(arg, audio)

    async def _text(self, arg: str) -> str:
        if not arg:
            return "usage: text <text>"
        return await self._speak(arg, None)

    async def _speak(self, text: str, audio: SpeechAudio | None) -> str:
        result = await self.body.speak(text, audio, "happy")
        if not result.delivered:
            return f"not delivered: {result.error}"
        if not result.finished:
            return f"delivered, but: {result.error}"
        return f"spoken: pet played {result.duration_ms} ms (total {result.elapsed_ms} ms)"

    async def _caption(self, arg: str) -> str:
        return _format(await self.body.show_caption(arg or None))

    async def _out(self, arg: str) -> str:
        exit_name = arg or "jump_out"
        if exit_name not in EXITS:
            return f"exit must be one of: {' '.join(EXITS)}"
        return _format(await self.body.deactivate(exit_name))  # type: ignore[arg-type]

    async def _in(self, arg: str) -> str:
        entrance = arg or "jump_in"
        if entrance not in ENTRANCES:
            return f"entrance must be one of: {' '.join(ENTRANCES)}"
        return _format(await self.body.activate(entrance))  # type: ignore[arg-type]

    async def _status(self, _arg: str) -> str:
        return f"{self.body.name}: {self.body.health()}"

    async def _help(self, _arg: str) -> str:
        return HELP


def _tts_voice(loaded: LoadedConfig) -> Synthesize:
    """Real TTS voice with a timeout; falls back to babble so the tool never gets stuck."""
    from pipi_brain.openai_client import create_openai_client
    from pipi_brain.speech.tts import OpenAITextToSpeech

    api_key = loaded.secrets.openai_api_key
    if api_key is None:
        raise ConfigError("--tts needs OPENAI_API_KEY in .env")
    app = loaded.app
    tts = OpenAITextToSpeech(
        create_openai_client(api_key), model=app.models.tts, voice=app.models.tts_voice
    )

    async def speak(text: str) -> SpeechAudio:
        outcome = await timed_call(lambda: tts.synthesize(text), app.timeouts.tts_s)
        if outcome.ok and outcome.value is not None:
            return outcome.value
        print(f"  [tts failed: {outcome.error}] -> babble voice")
        return babble(text)

    return speak


BODY_CHOICES: Mapping[str, str] = {"pet": "desktop_pet", "robot": "fake_robot"}
START_HINTS: Mapping[str, str] = {
    "desktop_pet": "Start the pet: cd desktop-pet ; npm run dev",
    "fake_robot": "Open the fake robot: cd web ; npm run dev -> http://localhost:5173/fake-robot/",
}


async def run(
    loaded: LoadedConfig, *, participant: str, use_tts: bool, body_name: str = "desktop_pet"
) -> None:
    from pipi_brain.voice_app import TerminalTextInput

    app = loaded.app
    synthesize = _tts_voice(loaded) if use_tts else babble_voice
    logger = StudyLogger(app.logging.dir, participant)

    def log_for(name: str) -> Callable[[str, Mapping[str, Any]], None]:
        def log(event_type: str, data: Mapping[str, Any]) -> None:
            logger.log(event_type, data, body=name)

        return log

    logger.log(
        "session_start",
        {
            "mode": app.mode,
            "config_hash": loaded.config_hash,
            "runner": "pet_cli",
            "body": body_name,
            "robot_side": app.pet.robot_side,
            "voice": "tts-1" if use_tts else "babble",
        },
    )
    # Both WebSocket bodies may connect (pet + fake robot); the CLI drives one of them.
    server = BodyServer.from_config(app, log=log_for(body_name), log_for=log_for)
    body = server.bodies[body_name]
    cli = PetCli(body, synthesize)
    reason = "interrupted"
    async with server:
        print(f"{body_name} control on {server.url}  (log: {logger.folder})")
        print(f"{START_HINTS[body_name]}     (type help for commands)")
        if await body.wait_connected(app.bodies.connect_wait_s):
            print(f"{body_name} connected.")
        else:
            print(f"No {body_name} yet; commands will fail until it connects.")
        text_input = TerminalTextInput(f"{body_name}> ")
        try:
            while True:
                line = await text_input.read_line()
                output = await cli.execute(line) if line is not None else None
                if output is None:
                    reason = "quit"
                    break
                if output:
                    print(output)
        finally:
            logger.log("session_end", {"reason": reason})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipi_brain.tools.pet_cli", description="Drive the desktop pet by hand."
    )
    parser.add_argument("--config", required=True, help="e.g. ../config/dev.yaml")
    parser.add_argument("--participant", default="PETCLI", help="log folder name prefix")
    parser.add_argument("--tts", action="store_true", help="use the real tts-1 voice for 'say'")
    parser.add_argument(
        "--body",
        choices=sorted(BODY_CHOICES),
        default="pet",
        help="which body to drive: the desktop pet or the fake robot web page",
    )
    args = parser.parse_args(argv)
    try:
        loaded = load_config(args.config)
        asyncio.run(
            run(
                loaded,
                participant=args.participant,
                use_tts=args.tts,
                body_name=BODY_CHOICES[args.body],
            )
        )
    except (ConfigError, LoggerError, BodyServerError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
