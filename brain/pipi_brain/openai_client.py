"""The single place where the OpenAI client is created from the API key.

The key comes only from ``Secrets`` (``.env`` / environment) and is unwrapped here, right
before it is handed to the SDK. It is never printed, logged or stored anywhere else.
SDK retries are off: our own code decides on retries and fallbacks (see resilience.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

if TYPE_CHECKING:
    from openai import AsyncOpenAI

# Our own asyncio timeouts are shorter; this only stops a hung connection living forever.
SDK_TIMEOUT_S = 30.0


def create_openai_client(api_key: SecretStr) -> AsyncOpenAI:
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key.get_secret_value(), max_retries=0, timeout=SDK_TIMEOUT_S)
