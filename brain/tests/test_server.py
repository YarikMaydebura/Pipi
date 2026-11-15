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
from pipi_brain.bodies.fake_robot import FakeRobotBody
from pipi_brain.config import LoadedConfig
from pipi_brain.protocol import Hello, encode
from pipi_brain.server import BodyServer, BodyServerError, origin_allowed

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


# --- several bodies at once (M3: desktop pet + fake robot) -----------------------------------

ROBOT_HELLO = encode(Hello(body="fake_robot", version="0.1.0"))


@pytest.fixture
async def both() -> AsyncIterator[tuple[BodyServer, EventLog]]:
    log = EventLog()
    bodies = {
        "desktop_pet": DesktopPetBody(SETTINGS, robot_side="left", log=log),
        "fake_robot": FakeRobotBody(SETTINGS, log=log),
    }
    server = BodyServer(host="127.0.0.1", port=0, bodies=bodies, hello_timeout_s=0.2, log=log)
    async with server:
        yield server, log


async def answer(client: ClientConnection, *, speech_done_ms: int | None = None) -> dict[str, Any]:
    """Ack the next brain message; for speak also report speech_done, like the bodies do."""
    message = await ack_next(client)
    if speech_done_ms is not None and message["type"] == "speak":
        done = {"type": "speech_done", "id": f"done-{message['id']}", "ts": 1}
        await client.send(json.dumps({**done, "ref_id": message["id"], "duration_ms": 42}))
    return message


async def test_bodies_mapping_is_read_only_and_exists_before_anyone_connects(
    both: tuple[BodyServer, EventLog],
) -> None:
    server, _ = both
    assert sorted(server.bodies) == ["desktop_pet", "fake_robot"]
    assert not any(body.connected for body in server.bodies.values())
    with pytest.raises(TypeError):
        server.bodies["alpha_mini"] = server.bodies["fake_robot"]  # type: ignore[index]


async def test_pet_and_fake_robot_are_connected_together(
    both: tuple[BodyServer, EventLog],
) -> None:
    server, _ = both
    pet, robot = server.bodies["desktop_pet"], server.bodies["fake_robot"]
    async with connect(server.url) as pet_client, connect(server.url) as robot_client:
        await pet_client.send(HELLO)
        assert (await ack_next(pet_client))["type"] == "body_config"
        await robot_client.send(ROBOT_HELLO)
        assert await robot.wait_connected(1) and pet.connected
        assert robot.health() == "connected (fake robot 0.1.0)"

        wake = asyncio.create_task(robot.activate("wake_up"))
        assert (await answer(robot_client))["entrance"] == "wake_up"
        assert (await wake).ok
        eyes = asyncio.create_task(pet.set_eyes("sleepy"))
        assert (await answer(pet_client))["state"] == "sleepy"
        assert (await eyes).ok

        speak = asyncio.create_task(robot.speak("Ta-da!", None, "happy"))
        assert (await answer(robot_client, speech_done_ms=42))["text"] == "Ta-da!"
        result = await speak
        assert result.finished and result.duration_ms == 42

        sleep = asyncio.create_task(robot.deactivate("sleep"))
        assert (await answer(robot_client))["exit"] == "sleep"
        assert (await sleep).ok


async def test_the_fake_robot_never_gets_the_pets_body_config(
    both: tuple[BodyServer, EventLog],
) -> None:
    server, _ = both
    async with connect(server.url) as client:
        await client.send(ROBOT_HELLO)
        assert await server.bodies["fake_robot"].wait_connected(1)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.recv(), 0.1)


async def test_a_new_connection_replaces_only_the_same_body(
    both: tuple[BodyServer, EventLog],
) -> None:
    server, log = both
    pet, robot = server.bodies["desktop_pet"], server.bodies["fake_robot"]
    async with connect(server.url) as pet_client, connect(server.url) as old_robot:
        await pet_client.send(HELLO)
        await ack_next(pet_client)
        await old_robot.send(ROBOT_HELLO)
        assert await robot.wait_connected(1)
        async with connect(server.url) as new_robot:
            await new_robot.send(ROBOT_HELLO)
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(old_robot.recv(), 1)  # the old robot page is closed
            assert robot.connected and pet.connected
            motion = asyncio.create_task(robot.play_motion("nod"))
            assert (await answer(new_robot))["name"] == "nod"
            assert (await motion).ok
    replaced = [d for kind, d in log.events if kind == "body_disconnected"]
    assert any(d["reason"] == "replaced by a new connection" for d in replaced)


def test_from_config_creates_both_bodies(dev_config: LoadedConfig) -> None:
    app = dev_config.app
    logged: list[str] = []
    server = BodyServer.from_config(
        app, log=EventLog(), log_for=lambda name: lambda kind, _data: logged.append(name)
    )
    assert isinstance(server.bodies["desktop_pet"], DesktopPetBody)
    assert isinstance(server.bodies["fake_robot"], FakeRobotBody)
    assert server.url.endswith(f":{app.server.port}")


@pytest.mark.parametrize(
    ("origin", "host", "allowed"),
    [
        (None, "127.0.0.1:8765", True),  # Python clients, tests
        ("file://", "127.0.0.1:8765", True),  # packaged Electron pet
        ("null", "127.0.0.1:8765", True),
        ("http://localhost:5173", "127.0.0.1:8765", True),  # Vite dev server
        ("http://127.0.0.1:8080", "127.0.0.1:8765", True),  # brain's web server, same laptop
        ("http://192.168.1.20:8080", "192.168.1.20:8765", True),  # page from this laptop, LAN
        ("http://10.0.0.7", "10.0.0.7:8765", True),
        ("http://yariks-mac.local:8080", "yariks-mac.local:8765", True),
        ("http://192.168.1.99:8080", "192.168.1.20:8765", False),  # another LAN machine's page
        ("https://evil.example", "127.0.0.1:8765", False),
        ("http://evil.example:8765", "evil.example:8765", False),  # DNS rebinding
        ("http://8.8.8.8", "8.8.8.8:8765", False),  # public IP
        ("http://192.168.1.20:8080", None, False),
        ("http://localhost.evil.example", "127.0.0.1:8765", False),
    ],
)
def test_origin_rules(origin: str | None, host: str | None, allowed: bool) -> None:
    assert origin_allowed(origin, host) is allowed
