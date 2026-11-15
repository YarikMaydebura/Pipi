"""Speech-to-text with gpt-4o-mini-transcribe (model name comes from config.models.stt)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI


class OpenAISpeechToText:
    def __init__(self, client: AsyncOpenAI, *, model: str, language: str = "en") -> None:
        self._client = client
        self._model = model
        self._language = language

    async def transcribe(self, wav: bytes) -> str:
        result = await self._client.audio.transcriptions.create(
            model=self._model,
            file=("utterance.wav", wav, "audio/wav"),
            language=self._language,
            response_format="json",
        )
        return result.text.strip()
