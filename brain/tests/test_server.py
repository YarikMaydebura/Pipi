"""The body WebSocket server with a real (local, loopback) client acting as the pet."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from pipi_brain.bodies.desktop_pet import DesktopPetBody
from pipi_brain.protocol import Hello, encode
from pipi_brain.server import BodyServer, BodyServerError

from .test_bodies import SETTINGS, EventLog

HELLO = encode(Hello(body="desktop_pet", version="0.1.0"))


@pytest.fixture
async def running() -> AsyncIterator[tuple[BodyServer, DesktopPetBody, EventLog]]:
    log = EventLog()
    pet = DesktopPetBody(SETTINGS, robot_side="right", log=log)
    server = BodyServer(
        host="127.0.0.1",
        port=0,
        bodies={"desktop_pet": pet},
        hello_timeout_s=0.2,
        log=log,
    )
    async with server:
        yield server, pet, log


async def ack_next(client: ClientConnection) -> dict[str, Any]:
    """Receive one brain message and ack it like the pet does."""
    message = json.loads(await asyncio.wait_for(client.recv(), 1))
    ack = {"type": "ack", "id": f"ack-{message['id']}", "ts": 1, "ref_id": message["id"]}
    await client.send(json.dumps({**ack, "ok": True}))
    return message


async def test_pet_connects_gets_its_config_and_acks_commands(
    running: tuple[BodyServer, DesktopPetBody, EventLog],
) -> None:
    server, pet, log = running
    async with connect(server.url) as client:
        await client.send(HELLO)
        config = await ack_next(client)
        assert config == {**config, "type": "body_config", "robot_side": "right"}
        eyes_task = asyncio.create_task(pet.set_eyes("listening"))
        eyes = await ack_next(client)
        assert eyes["state"] == "listening"
        assert (await eyes_task).ok
    await asyncio.sleep(0.05)
    assert not pet.connected
    assert [e for e in log.events if e[0] == "body_disconnected"]


async def test_invalid_frames_are_logged_and_ignored(
    running: tuple[BodyServer, DesktopPetBody, EventLog],
) -> None:
    server, pet, log = running
    async with connect(server.url) as client:
        await client.send(HELLO)
        await ack_next(client)
        await client.send("{not json")
        await client.send(json.dumps({"type": "dance", "id": "x", "ts": 1}))
        await client.send(HELLO)
        await asyncio.sleep(0.05)
        assert pet.connected
    errors = [d["error"] for kind, d in log.events if kind == "body_error"]
    assert sum("invalid message" in e for e in errors) == 2
    assert "repeated hello" in errors


async def test_a_connection_without_hello_is_closed(
    running: tuple[BodyServer, DesktopPetBody, EventLog],
) -> None:
    server, pet, log = running
    async with connect(server.url) as client:
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(client.recv(), 1)
    assert not pet.connected
    assert any("no hello" in d.get("error", "") for _, d in log.events)


async def test_an_unexpected_body_is_turned_away(
    running: tuple[BodyServer, DesktopPetBody, EventLog],
) -> None:
    server, _, _ = running
    async with connect(server.url) as client:
        await client.send(encode(Hello(body="fake_robot", version="0.1.0")))
        with pytest.raises(ConnectionClosed) as closed:
            await asyncio.wait_for(client.recv(), 1)
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 1008


async def test_web_pages_from_other_sites_cannot_connect(
    running: tuple[BodyServer, DesktopPetBody, EventLog],
) -> None:
    server, _, _ = running
    with pytest.raises(InvalidStatus):
        async with connect(server.url, origin="https://evil.example"):  # type: ignore[arg-type]
            pass
    async with connect(server.url, origin="http://localhost:5173") as client:  # type: ignore[arg-type]
        await client.send(HELLO)
        await ack_next(client)


async def test_port_in_use_gives_a_readable_error(
    running: tuple[BodyServer, DesktopPetBody, EventLog],
) -> None:
    server, pet, log = running
    second = BodyServer(host="127.0.0.1", port=server.port, bodies={}, hello_timeout_s=1, log=log)
    with pytest.raises(BodyServerError, match="another brain"):
        await second.start()
