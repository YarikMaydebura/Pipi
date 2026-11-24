"""A full session WITHOUT the OpenAI API: for trying the games and as a demo backup.

Run: ``python -m pipi_brain.tools.offline_session --config ../config/dev.yaml``

Same session as ``--session --typed`` (body server, pet, fake robot, WoZ ``/commands``), but:
- no LLM: every LLM call fails at once, so Pipi uses its scripted fallback lines, the game
  menu uses the keyword map, Crocodile picks words at random and judges guesses with the
  synonym lists (that is exactly what happens in a real session when the network is down),
- no real voice: the synthetic "babble" voice (captions show the text),
- typed input: type what you would say; in the duel, Enter is the bang.

Jump straight to the games with ``/goto GAME_CROCODILE`` or ``/goto GAME_MENU``.
No API key is read and nothing is sent to the network.

Demo backup (same flags as the normal session): ``--woz`` also serves the WoZ panel
(http://127.0.0.1:8766/woz/, needs ``npm run build``) and waits for Start there;
``--persona cheerful`` skips the persona question.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import sys
from collections.abc import Sequence
from pathlib import Path

from pipi_brain.config import ConfigError, LoadedConfig, load_config
from pipi_brain.dialogue.llm import DialogueEngine, LlmError
from pipi_brain.dialogue.prompts import ChatMessage
from pipi_brain.logging_study import LoggerError
from pipi_brain.session_app import SessionAppOptions, run_session
from pipi_brain.speech.audio_gate import AudioGate
from pipi_brain.speech.base import SpeechAudio
from pipi_brain.tools.babble import babble
from pipi_brain.voice_app import Health, SessionOptions, TerminalTextInput
from pipi_brain.voice_loop import VoiceLoopDeps
from pipi_brain.woz_server import serve_woz


class OfflineChatModel:
    async def complete_json(self, messages: Sequence[ChatMessage]) -> str:
        raise LlmError("offline session: no LLM")


class OfflineSpeechToText:
    async def transcribe(self, wav: bytes) -> str:
        raise LlmError("offline session: no speech-to-text (typed input only)")


class BabbleTextToSpeech:
    async def synthesize(self, text: str) -> SpeechAudio:
        return babble(text)


class SilentSpeaker:
    """No laptop audio: without a body the lines are only printed in the terminal."""

    async def play(self, audio: SpeechAudio) -> None:
        return None

    def stop(self) -> None:
        return None


async def offline_deps(
    loaded: LoadedConfig, options: SessionOptions, gate: AudioGate
) -> tuple[VoiceLoopDeps, Health]:
    deps = VoiceLoopDeps(
        stt=OfflineSpeechToText(),
        tts=BabbleTextToSpeech(),
        speaker=SilentSpeaker(),
        dialogue=DialogueEngine(OfflineChatModel(), timeout_s=1, retries=0),
        text_input=TerminalTextInput(),
        audio_input=None,
    )
    health: Health = {
        "openai_key": "not used (offline session)",
        "llm": "off: scripted fallback lines + keyword fallbacks",
        "voice": "synthetic babble",
        "microphone": "not used (typed input)",
    }
    return deps, health


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="offline_session", description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="e.g. ../config/dev.yaml")
    parser.add_argument("--participant", default="OFFLINE", help="log folder name prefix")
    parser.add_argument("--persona", default=None, help="fixed persona id: no persona question")
    parser.add_argument(
        "--no-camera",
        action="store_true",
        help="never use the webcam (the staring contest pretends), e.g. without camera consent",
    )
    parser.add_argument(
        "--woz", action="store_true", help="serve the WoZ panel and wait for Start there"
    )
    args = parser.parse_args(argv)
    try:
        loaded = load_config(args.config)
        # The babble voice must never be stored in the cache of the real voice.
        app = loaded.app.model_copy(
            update={"tts_cache": loaded.app.tts_cache.model_copy(update={"enabled": False})}
        )
        loaded = LoadedConfig(app, loaded.secrets, loaded.source, loaded.config_hash)
        options = SessionAppOptions(
            participant_id=args.participant,
            persona_id=args.persona,
            typed_input=True,
            camera=not args.no_camera,
        )
        woz_factory = functools.partial(serve_woz, loaded=loaded) if args.woz else None
        print("Offline session: no LLM, babble voice. Try: /goto GAME_CROCODILE   /help")
        asyncio.run(
            run_session(loaded, options, woz_server_factory=woz_factory, deps_factory=offline_deps)
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    except (ConfigError, LoggerError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
