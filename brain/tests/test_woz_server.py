"""The WoZ server with a fake backend and a real local WebSocket client acting as the panel."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus

from pipi_brain.config import LoadedConfig, WozConfig, load_config
from pipi_brain.protocol import Alert, BrainToWoz, StateUpdate, Turn, WozCommand
from pipi_brain.woz_api import CommandOutcome
from pipi_brain.woz_server import (
    WozServer,
    WozServerError,
    is_loopback_host,
    origin_allowed,
    serve_woz,
    token_matches,
    weak_token,
)

from .conftest import CONFIG_DIR

TOKEN = "test-token-1234567890"


class FakeBackend:
    """Implements WozBackend: records commands, publishes events on demand."""

    def __init__(self) -> None:
        self.state = StateUpdate(phase="FOCUS", mode="dev", participant_id="DEV")
        self.commands: list[WozCommand] = []
        self.listeners: list[Callable[[BrainToWoz], None]] = []
        self.delay_s = 0.0
        self.outcome = CommandOutcome(ok=True)
        self.raise_on_command = False

    def snapshot(self) -> StateUpdate:
        return self.state

    async def handle_woz(self, command: WozCommand) -> CommandOutcome:
        self.commands.append(command)
        if self.raise_on_command:
            raise RuntimeError("boom")
        if command.command != "emergency_stop":
            await asyncio.sleep(self.delay_s)
        return self.outcome

    def subscribe(self, listener: Callable[[BrainToWoz], None]) -> Callable[[], None]:
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def publish(self, message: BrainToWoz) -> None:
        for listener in list(self.listeners):
            listener(message)


class EventLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_type: str, data: Mapping[str, Any]) -> None:
        self.events.append((event_type, dict(data)))

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [data for event_type, data in self.events if event_type == kind]


def settings(dist: Path, **overrides: Any) -> WozConfig:
    values: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 0,
        "max_panels": 2,
        "web_dist": dist,
        "command_timeout_s": 1.0,
    }
    # port 0 = any free port (the real config requires >= 1024), so skip validation here
    return WozConfig.model_construct(**{**values, **overrides})


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "woz").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "woz" / "index.html").write_text("<h1>panel</h1>", encoding="utf-8")
    (root / "assets" / "woz-abc.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return root


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def log() -> EventLog:
    return EventLog()


@pytest.fixture
async def server(dist: Path, backend: FakeBackend, log: EventLog) -> AsyncIterator[WozServer]:
    async with WozServer(backend, settings=settings(dist), token=None, log=log) as running:
        yield running


def ws_url(server: WozServer, token: str | None = None) -> str:
    query = f"?token={token}" if token is not None else ""
    return f"ws://127.0.0.1:{server.port}/ws/woz{query}"


async def recv(client: ClientConnection) -> dict[str, Any]:
    return json.loads(await asyncio.wait_for(client.recv(), 2))


def command(name: str = "pause", **fields: Any) -> dict[str, Any]:
    message = {"type": "woz_command", "id": f"cmd-{name}", "ts": 1, "command": name}
    return {"reason": "timing", "args": {}, **message, **fields}


async def http_get(server: WozServer, path: str) -> tuple[int, dict[str, str], bytes]:
    def fetch() -> tuple[int, dict[str, str], bytes]:
        opener = urllib.request.build_opener(NoRedirect)
        url = f"http://127.0.0.1:{server.port}{path}"
        try:
            with opener.open(url, timeout=2) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    return await asyncio.to_thread(fetch)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


# --- panel channel ---------------------------------------------------------------------------


async def test_snapshot_comes_first_then_events_are_forwarded(
    server: WozServer, backend: FakeBackend, log: EventLog
) -> None:
    async with connect(ws_url(server)) as client:
        first = await recv(client)
        assert first["type"] == "state_update"
        assert first["phase"] == "FOCUS"
        backend.publish(Turn(speaker="user", text="hello"))
        backend.publish(Alert(level="warning", message="robot slow"))
        assert (await recv(client))["text"] == "hello"
        assert (await recv(client))["message"] == "robot slow"
        assert server.panel_count == 1
    await asyncio.sleep(0.05)
    assert server.panel_count == 0
    assert backend.listeners == []
    assert log.of("woz_connected")[0]["panels"] == 1
    assert log.of("woz_disconnected")[0]["panels"] == 0


async def test_command_is_handled_acked_and_logged_with_reason(
    server: WozServer, backend: FakeBackend, log: EventLog
) -> None:
    async with connect(ws_url(server)) as client:
        await recv(client)
        await client.send(json.dumps(command("goto_phase", args={"phase": "CHAT"})))
        ack = await recv(client)
    assert ack == {**ack, "type": "ack", "ref_id": "cmd-goto_phase", "ok": True, "error": None}
    assert backend.commands[0].args == {"phase": "CHAT"}
    logged = log.of("woz_command")[0]
    assert logged == {**logged, "command": "goto_phase", "reason": "timing", "note": None}
    assert log.of("woz_ack")[0]["ok"] is True


async def test_backend_failure_and_exception_become_error_acks(
    server: WozServer, backend: FakeBackend
) -> None:
    async with connect(ws_url(server)) as client:
        await recv(client)
        backend.outcome = CommandOutcome(ok=False, error="unknown line id")
        await client.send(json.dumps(command("say", args={"line_id": "nope"})))
        assert (await recv(client))["error"] == "unknown line id"
        backend.raise_on_command = True
        await client.send(json.dumps(command("next_phase")))
        ack = await recv(client)
    assert ack["ok"] is False
    assert "RuntimeError" in ack["error"]


async def test_emergency_stop_is_not_blocked_by_a_slow_command(
    server: WozServer, backend: FakeBackend
) -> None:
    backend.delay_s = 0.5
    async with connect(ws_url(server)) as client:
        await recv(client)
        await client.send(json.dumps(command("trigger_migration_out")))
        await client.send(json.dumps(command("emergency_stop")))
        first = await recv(client)
        second = await recv(client)
    assert first["ref_id"] == "cmd-emergency_stop"
    assert second["ref_id"] == "cmd-trigger_migration_out"


async def test_slow_command_gets_timeout_ack_and_late_result(
    dist: Path, backend: FakeBackend, log: EventLog
) -> None:
    backend.delay_s = 0.3
    config = settings(dist, command_timeout_s=0.1)
    server = WozServer(backend, settings=config, token=None, log=log)
    async with server, connect(ws_url(server)) as client:
        await recv(client)
        await client.send(json.dumps(command("end_game")))
        ack = await recv(client)
        late = await recv(client)
    assert ack["ok"] is False
    assert "may still be running" in ack["error"]
    assert late["type"] == "alert"
    assert "finished late: ok" in late["message"]
    assert [a.get("late", False) for a in log.of("woz_ack")] == [False, True]


async def test_invalid_frames_are_answered_and_logged_never_crash(
    server: WozServer, backend: FakeBackend, log: EventLog
) -> None:
    async with connect(ws_url(server)) as client:
        await recv(client)
        await client.send("{not json")
        assert (await recv(client))["type"] == "alert"
        await client.send(json.dumps(command("dance")))
        bad = await recv(client)
        assert bad == {**bad, "type": "ack", "ref_id": "cmd-dance", "ok": False}
        await client.send(json.dumps(command("pause", reason="other")))
        no_note = await recv(client)
        assert "note is required" in no_note["error"]
        await client.send(b"\x00\x01")
        assert (await recv(client))["type"] == "alert"
        await client.send(json.dumps(command("resume")))
        assert (await recv(client))["ok"] is True  # still alive
    assert len(log.of("woz_invalid")) == 4
    assert [c.command for c in backend.commands] == ["resume"]


async def test_note_with_reason_other_is_accepted_and_logged(
    server: WozServer, log: EventLog
) -> None:
    async with connect(ws_url(server)) as client:
        await recv(client)
        await client.send(json.dumps(command("pause", reason="other", note="fire alarm")))
        assert (await recv(client))["ok"] is True
    assert log.of("woz_command")[0]["note"] == "fire alarm"


async def test_snapshot_failure_sends_an_alert_instead(
    server: WozServer, backend: FakeBackend
) -> None:
    def broken() -> StateUpdate:
        raise RuntimeError("not ready")

    backend.snapshot = broken  # type: ignore[method-assign]
    async with connect(ws_url(server)) as client:
        first = await recv(client)
    assert first["type"] == "alert"
    assert "not ready" in first["message"]


# --- security --------------------------------------------------------------------------------


async def test_token_is_required_when_set(dist: Path, backend: FakeBackend, log: EventLog) -> None:
    async with WozServer(
        backend, settings=settings(dist), token=SecretStr(TOKEN), log=log
    ) as server:
        for token in (None, "wrong"):
            with pytest.raises(InvalidStatus) as info:
                async with connect(ws_url(server, token)):
                    pass
            assert info.value.response.status_code == 401
        async with connect(ws_url(server, TOKEN)) as client:
            assert (await recv(client))["type"] == "state_update"
    rejected = log.of("woz_rejected")
    assert len(rejected) == 2
    assert TOKEN not in json.dumps(log.events)


async def test_refuses_to_start_on_the_lan_without_a_strong_token(
    dist: Path, backend: FakeBackend, log: EventLog
) -> None:
    lan = settings(dist, host="0.0.0.0")
    with pytest.raises(WozServerError, match="WOZ_TOKEN is not set"):
        await WozServer(backend, settings=lan, token=None, log=log).start()
    with pytest.raises(WozServerError, match="too weak"):
        await WozServer(backend, settings=lan, token=SecretStr("change-me"), log=log).start()


async def test_foreign_origin_is_rejected(server: WozServer, log: EventLog) -> None:
    with pytest.raises(InvalidStatus) as info:
        async with connect(ws_url(server), origin="http://evil.example"):  # type: ignore[arg-type]
            pass
    assert info.value.response.status_code == 403
    assert log.of("woz_rejected")[0]["reason"] == "origin not allowed"


async def test_same_origin_page_is_allowed(server: WozServer) -> None:
    origin = f"http://127.0.0.1:{server.port}"
    async with connect(ws_url(server), origin=origin) as client:  # type: ignore[arg-type]
        assert (await recv(client))["type"] == "state_update"


async def test_panel_limit(server: WozServer, log: EventLog) -> None:
    async with connect(ws_url(server)) as one, connect(ws_url(server)) as two:
        await recv(one)
        await recv(two)
        with pytest.raises(InvalidStatus) as info:
            async with connect(ws_url(server)):
                pass
        assert info.value.response.status_code == 503
    assert log.of("woz_rejected")[0]["reason"] == "too many panels connected"


def test_origin_rules() -> None:
    assert origin_allowed(None, "x")
    assert origin_allowed("http://localhost:5173", "192.168.1.5:8766")
    assert origin_allowed("http://192.168.1.5:8766", "192.168.1.5:8766")
    assert not origin_allowed("http://192.168.1.9:8766", "192.168.1.5:8766")
    assert not origin_allowed("null", "192.168.1.5:8766")
    assert not origin_allowed("file://", None)


def test_token_and_host_helpers() -> None:
    assert token_matches(None, None)
    assert not token_matches(SecretStr(TOKEN), None)
    assert not token_matches(SecretStr(TOKEN), TOKEN + "x")
    assert token_matches(SecretStr(TOKEN), TOKEN)
    assert weak_token(SecretStr("short"))
    assert weak_token(SecretStr("Change-Me"))
    assert not weak_token(SecretStr(TOKEN))
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.5")


# --- static files ----------------------------------------------------------------------------


async def test_serves_the_built_panel_with_security_headers(server: WozServer) -> None:
    status, headers, body = await http_get(server, "/woz/?token=abc")
    assert status == 200
    assert body == b"<h1>panel</h1>"
    assert headers["Content-Type"].startswith("text/html")
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    status, headers, _ = await http_get(server, "/assets/woz-abc.js")
    assert status == 200
    assert headers["Content-Type"].startswith("text/javascript")
    assert "immutable" in headers["Cache-Control"]


async def test_redirects_keep_the_token(server: WozServer) -> None:
    status, headers, _ = await http_get(server, "/?token=abc")
    assert (status, headers["Location"]) == (302, "/woz/?token=abc")
    status, headers, _ = await http_get(server, "/woz?token=abc")
    assert (status, headers["Location"]) == (302, "/woz/?token=abc")


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/nope.js", "/x%00"])
async def test_no_files_outside_dist_and_404s(server: WozServer, path: str) -> None:
    status, _, body = await http_get(server, path)
    assert status == 404
    assert b"outside" not in body


async def test_missing_dist_explains_how_to_build(
    tmp_path: Path, backend: FakeBackend, log: EventLog
) -> None:
    config = settings(tmp_path / "no-dist")
    async with WozServer(backend, settings=config, token=None, log=log) as server:
        assert not server.web_app_built
        status, _, body = await http_get(server, "/woz/")
    assert status == 503
    assert b"npm run build" in body
    assert log.of("woz_server_start")[0]["web_app_built"] is False


async def test_plain_http_on_the_socket_path_is_rejected(server: WozServer) -> None:
    status, _, _ = await http_get(server, "/ws/woz")
    assert status == 400


# --- serve_woz + config ----------------------------------------------------------------------


async def test_serve_woz_uses_config_and_never_announces_the_token(
    tmp_path: Path, backend: FakeBackend, log: EventLog
) -> None:
    loaded = load_config(CONFIG_DIR / "dev.yaml")
    app = loaded.app.model_copy(update={"woz": settings(tmp_path / "no-dist")})
    loaded = replace(
        loaded,
        app=app,
        secrets=loaded.secrets.model_copy(update={"woz_token": SecretStr(TOKEN)}),
    )
    lines: list[str] = []
    async with serve_woz(backend, loaded, log, announce=lines.append) as server:
        assert server.token_required
        async with connect(ws_url(server, TOKEN)) as client:
            assert (await recv(client))["type"] == "state_update"
    assert "token=<WOZ_TOKEN>" in lines[0]
    assert "npm run build" in lines[1]
    assert TOKEN not in "\n".join(lines)


def _loaded(mode: str) -> LoadedConfig:
    return load_config(CONFIG_DIR / f"{mode}.yaml")


def test_woz_config_defaults_and_mode_overrides() -> None:
    dev = _loaded("dev").app.woz
    assert (dev.host, dev.port) == ("127.0.0.1", 8766)
    assert dev.web_dist == CONFIG_DIR.parent / "web" / "dist"
    assert dev.max_panels >= 1
    assert _loaded("study").app.woz.host == "0.0.0.0"
    assert _loaded("demo").app.woz.host == "0.0.0.0"
