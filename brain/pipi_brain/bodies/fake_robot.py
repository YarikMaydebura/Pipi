"""The fake robot as a Body: a web page (web/src/fake-robot/) that pretends to be the Alpha Mini.

It speaks exactly the same WebSocket protocol as the desktop pet, so the session logic cannot
tell the difference: ``activate("wake_up")`` / ``deactivate("sleep")`` are acked when the
wake / sleep animation has finished, ``speak`` plays the WAV audio in the browser and ends
with ``speech_done``. It gets no ``body_config`` (the robot side only matters to the pet).

Used before lab access, for the Nov 20 presentation, and as the demo-day backup body.
"""

from __future__ import annotations

from pipi_brain.bodies.websocket_body import WebSocketBody


class FakeRobotBody(WebSocketBody):
    name = "fake_robot"
    label = "fake robot"
