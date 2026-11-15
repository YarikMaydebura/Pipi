"""The simulated session behind ``tools.woz_demo`` (used to try the panel by hand)."""

from __future__ import annotations

from pipi_brain.protocol import BrainToWoz, WozCommand
from pipi_brain.tools.woz_demo import DemoBackend


def cmd(name: str, **args: str | int) -> WozCommand:
    return WozCommand(command=name, args=args, reason="demo")  # type: ignore[arg-type]


async def test_demo_backend_follows_commands_and_publishes_updates() -> None:
    backend = DemoBackend("dev", focus_s=30)
    seen: list[BrainToWoz] = []
    unsubscribe = backend.subscribe(seen.append)
    assert (await backend.handle_woz(cmd("start_session"))).ok
    assert not (await backend.handle_woz(cmd("start_session"))).ok
    assert (await backend.handle_woz(cmd("goto_phase", phase="FOCUS"))).ok
    assert backend.snapshot().active_body == "desktop_pet"
    assert (await backend.handle_woz(cmd("extend_focus", seconds=60))).ok
    timer = backend.snapshot().timer
    assert timer is not None and timer.remaining_s == 90
    assert not (await backend.handle_woz(cmd("goto_phase", phase="NOPE"))).ok
    assert (await backend.handle_woz(cmd("goto_phase", phase="CHAT"))).ok
    assert backend.snapshot().active_body == "fake_robot"
    assert not (await backend.handle_woz(cmd("extend_focus", seconds=10))).ok
    unsubscribe()
    assert {m.type for m in seen} == {"state_update"}
