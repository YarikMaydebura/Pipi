"""The desktop pet as a Body: protocol messages over the WebSocket server (server.py).

Everything a WebSocket body does (acks, timeouts, speech_done, logging) lives in
``websocket_body.py``. The pet adds one thing: right after ``hello`` it gets ``body_config``
with the screen edge that faces the robot (``pet.robot_side``), so it knows where to jump off.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from pipi_brain.bodies.base import BodyLog, BodyResult
from pipi_brain.bodies.channel import BodyLink
from pipi_brain.bodies.websocket_body import (
    MIN_CAPTION_S,
    WebSocketBody,
    caption_seconds,
    encode_audio_wav_b64,
)
from pipi_brain.config import BodiesConfig
from pipi_brain.protocol import BodyConfig, Hello, RobotSide

__all__ = ["MIN_CAPTION_S", "DesktopPetBody", "caption_seconds", "encode_audio_wav_b64"]


class DesktopPetBody(WebSocketBody):
    name = "desktop_pet"
    label = "pet"

    def __init__(
        self,
        settings: BodiesConfig,
        *,
        robot_side: RobotSide,
        log: BodyLog,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        super().__init__(settings, log=log, clock=clock)
        self._robot_side = robot_side
        self._tasks: set[asyncio.Task[BodyResult]] = set()

    def attach(self, link: BodyLink, hello: Hello) -> BodyLink | None:
        """A pet said hello: use it and send it its settings (robot side)."""
        previous = super().attach(link, hello)
        task = asyncio.get_running_loop().create_task(self.send_config())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return previous

    async def send_config(self) -> BodyResult:
        return await self.channel.request(
            BodyConfig(robot_side=self._robot_side),
            timeout_s=self._settings.ack_timeout_s,
            retries=self._settings.ack_retries,
        )
