"""Text-to-speech with tts-1 (model and voice come from config.models).

We ask for raw ``pcm`` output (24 kHz, 16-bit signed little-endian, mono), so no MP3 decoder
is needed and the audio can be played or streamed to a body as is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pipi_brain.speech.base import SpeechAudio

if TYPE_CHECKING:
    from openai import AsyncOpenAI

TTS_PCM_SAMPLE_RATE = 24000  # fixed by the OpenAI API for response_format="pcm"


class OpenAITextToSpeech:
    def __init__(self, client: AsyncOpenAI, *, model: str, voice: str) -> None:
        self._client = client
        self._model = model
        self._voice = voice

    async def synthesize(self, text: str) -> SpeechAudio:
        response = await self._client.audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
            response_format="pcm",
        )
        return SpeechAudio(pcm16=response.content, sample_rate=TTS_PCM_SAMPLE_RATE)
