"""Entry point: ``python -m pipi_brain --config ../config/dev.yaml``.

- Plain command (M0): load and validate the config, print a short summary, exit.
- ``--voice-loop`` (M1): talk to Pipi in the terminal (mic -> STT -> LLM -> TTS -> speaker).
  Add ``--typed`` to type instead of speaking. Ctrl+C ends the session and writes the log.
  Add ``--body pet`` (M2) to speak through the desktop pet (start it with ``npm run dev`` in
  desktop-pet/); without a pet the terminal + laptop speaker are used.
- ``--list-audio-devices``: print microphones/speakers (for ``audio.input_device``).

- ``--session`` (M3): the full study session (phases, pet + fake robot, migration); add
  ``--typed`` to type. Experimenter commands: ``/help`` in the terminal (or the WoZ panel).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from pipi_brain import __version__
from pipi_brain.config import ConfigError, LoadedConfig, load_config
from pipi_brain.logging_study import LoggerError

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_MISSING_KEY = 3
EXIT_AUDIO_ERROR = 4


def format_summary(loaded: LoadedConfig) -> str:
    """Human-readable config summary. Secrets are reported only as 'set' / 'missing'."""
    app = loaded.app
    secrets = loaded.secrets
    break_max = f"{app.timers.break_max_s} s" if app.timers.break_max_s else "no limit"
    enabled_cues = [name for name, on in app.cues.model_dump().items() if on]
    lines = [
        f"Pipi brain {__version__}",
        f"  config        : {loaded.source}  (hash {loaded.config_hash})",
        f"  mode          : {app.mode}",
        f"  server        : {app.server.host}:{app.server.port}",
        f"  robot body    : {app.robot.body}   (pet faces robot on the {app.pet.robot_side})",
        f"  timers        : focus {app.timers.focus_s} s, break max {break_max}",
        f"  models        : dialogue={app.models.dialogue}, stt={app.models.stt}, "
        f"tts={app.models.tts} (voice {app.models.tts_voice})",
        f"  logs          : {app.logging.dir}  (save_audio={app.logging.save_audio})",
        f"  cues on       : {', '.join(enabled_cues) or 'none'}",
        f"  OPENAI_API_KEY: {'set' if secrets.openai_api_key else 'missing'}",
        f"  WOZ_TOKEN     : {'set' if secrets.woz_token else 'missing'}",
    ]
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pipi_brain", description="Run the Pipi brain.")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a mode config, e.g. ../config/dev.yaml",
    )
    parser.add_argument(
        "--voice-loop", action="store_true", help="Talk to Pipi in the terminal (M1)."
    )
    parser.add_argument(
        "--session", action="store_true", help="Run the full session (M3, see session_app.py)."
    )
    parser.add_argument(
        "--typed",
        action="store_true",
        help="With --voice-loop / --session: type instead of speaking.",
    )
    parser.add_argument(
        "--woz",
        action="store_true",
        help="With --session: serve the WoZ panel and wait for the experimenter to start.",
    )
    parser.add_argument(
        "--body",
        choices=("terminal", "pet"),
        default="terminal",
        help="With --voice-loop: 'pet' speaks through the desktop pet (WebSocket server).",
    )
    parser.add_argument(
        "--participant", default="DEV", help="Pseudonymous participant id for the log (P01...)."
    )
    parser.add_argument("--persona", default=None, help="Persona id (default: from config).")
    parser.add_argument(
        "--max-turns", type=int, default=None, help="Stop after this many user turns."
    )
    parser.add_argument(
        "--list-audio-devices", action="store_true", help="Print audio devices and exit."
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        loaded = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if args.list_audio_devices:
        return _list_audio_devices()

    print(format_summary(loaded))
    if loaded.secrets.openai_api_key is None:
        print(
            "Warning: OPENAI_API_KEY is missing. Copy .env.example to .env and fill it in.",
            file=sys.stderr,
        )
        if args.voice_loop or args.session:
            return EXIT_MISSING_KEY
    if args.session:
        return _run_session(loaded, args)
    if not args.voice_loop:
        return EXIT_OK
    return _run_voice_loop(loaded, args)


def _list_audio_devices() -> int:
    from pipi_brain.speech.base import MicrophoneError
    from pipi_brain.speech.devices import describe_audio_devices

    try:
        print(describe_audio_devices())
    except MicrophoneError as exc:
        print(f"Audio error: {exc}", file=sys.stderr)
        return EXIT_AUDIO_ERROR
    return EXIT_OK


def _run_session(loaded: LoadedConfig, args: argparse.Namespace) -> int:
    from pipi_brain.session_app import SessionAppOptions, run_session

    options = SessionAppOptions(
        participant_id=args.participant, persona_id=args.persona, typed_input=args.typed
    )
    woz_factory = None
    if args.woz:
        import functools

        from pipi_brain.woz_server import serve_woz

        woz_factory = functools.partial(serve_woz, loaded=loaded)
    try:
        asyncio.run(run_session(loaded, options, woz_server_factory=woz_factory))
    except KeyboardInterrupt:
        print("\nStopped.")
    except (ConfigError, LoggerError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    return EXIT_OK


def _run_voice_loop(loaded: LoadedConfig, args: argparse.Namespace) -> int:
    from pipi_brain.voice_app import SessionOptions, run_voice_session

    options = SessionOptions(
        participant_id=args.participant,
        persona_id=args.persona,
        typed_input=args.typed,
        max_user_turns=args.max_turns,
        body=args.body,
    )
    try:
        asyncio.run(run_voice_session(loaded, options))
    except KeyboardInterrupt:
        print("\nStopped.")
    except (ConfigError, LoggerError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
