"""Entry point: ``python -m pipi_brain --config ../config/dev.yaml``.

M0: load and validate the config, print a short summary, exit. The server and the session
state machine are added in later milestones (see docs/ROADMAP.md).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pipi_brain import __version__
from pipi_brain.config import ConfigError, LoadedConfig, load_config

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2


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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        loaded = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    print(format_summary(loaded))
    if loaded.secrets.openai_api_key is None:
        print(
            "Warning: OPENAI_API_KEY is missing. Copy .env.example to .env and fill it in.",
            file=sys.stderr,
        )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
