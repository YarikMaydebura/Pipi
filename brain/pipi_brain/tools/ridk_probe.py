"""Probe a RidK robot (virtual or real Alpha Mini): what works, and how fast?

Run by hand only, with the robot paused in the portal (hamburger menu -> pause):

    python -m pipi_brain.tools.ridk_probe --realm rie.XXXXXXXX [--skip-motion] [--out DIR]

The realm can also come from RIDK_REALM in .env. Every RPC is timed and its result saved to
logs/ridk_probe/<timestamp>/results.json (logs/ is gitignored), next to any camera frame and
microphone recording it captured. Watch and listen to the robot while it runs: the script
prints what you should see or hear at each step, because some answers (did the eyes change?
did the beep play?) only a human can give. Copy the results into docs/ROBOT_RIDK.md.

RPC names and arguments follow the RidK "Manual Advanced Programming" (ROM + RIE API).
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import struct
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from autobahn.twisted.component import Component, run
    from autobahn.twisted.util import sleep
    from autobahn.wamp.exception import ApplicationError
    from twisted.internet import reactor
    from twisted.internet.defer import inlineCallbacks
except ImportError as exc:  # pragma: no cover - only hit without the robot extra installed
    sys.exit(f'Missing RidK deps ({exc}). Install them with:  pip install -e "brain[robot]"')

WAMP_URL = "wss://wamp.robotsindeklas.nl"
RPC_TIMEOUT_S = 30.0
HEARING_S = 3.0
SAY_TEXT = "Hi, I am Pipi. Can you hear me?"


def _out(*args: Any) -> None:
    """Print to the real terminal: autobahn's run() captures sys.stdout into its logger."""
    print(*args, file=sys.__stdout__, flush=True)


class Probe:
    """Runs the checks one by one and collects a JSON-friendly record of each."""

    def __init__(self, session: Any, out_dir: Path, skip_motion: bool) -> None:
        self.session = session
        self.out_dir = out_dir
        self.skip_motion = skip_motion
        self.results: list[dict[str, Any]] = []

    # -- helpers ---------------------------------------------------------------------------

    @inlineCallbacks
    def call(self, label: str, rpc: str, *, note: str = "", **kwargs: Any) -> Any:
        """Call one RPC with a timeout, print and record how it went, return its result."""
        if note:
            _out(f"\n>>> {note}")
        start = time.perf_counter()
        record: dict[str, Any] = {"label": label, "rpc": rpc, "args": _summarise(kwargs)}
        result = None
        try:
            d = self.session.call(rpc, **kwargs)
            d.addTimeout(RPC_TIMEOUT_S, reactor)
            result = yield d
            record["ok"] = True
            record["result"] = _summarise(result)
        except ApplicationError as exc:
            record["ok"] = False
            record["error"] = f"{exc.error}: {exc.args}"
        except Exception as exc:  # timeouts, transport errors: record and keep probing
            record["ok"] = False
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["ms"] = round((time.perf_counter() - start) * 1000)
        status = "OK  " if record["ok"] else "FAIL"
        detail = "" if record["ok"] else f"  -> {record['error']}"
        _out(f"[{status}] {label:<34} {record['ms']:>6} ms{detail}")
        self.results.append(record)
        return result

    def save_bytes(self, name: str, data: bytes) -> Path:
        path = self.out_dir / name
        path.write_bytes(data)
        _out(f"       saved {path} ({len(data)} bytes)")
        return path

    # -- checks ----------------------------------------------------------------------------

    @inlineCallbacks
    def wait_cloud_modules(self) -> Any:
        start = time.perf_counter()
        while time.perf_counter() - start < 15:
            try:
                yield self.session.call("rie.cloud_modules.ready")
                ms = round((time.perf_counter() - start) * 1000)
                _out(f"[OK  ] cloud modules ready                {ms:>6} ms")
                self.results.append({"label": "cloud modules ready", "ok": True, "ms": ms})
                return
            except ApplicationError:
                yield sleep(0.25)
        _out("[FAIL] cloud modules not ready after 15 s (dialogue/vision RPCs may fail)")
        self.results.append({"label": "cloud modules ready", "ok": False})

    @inlineCallbacks
    def info(self) -> Any:
        info = yield self.call("robot info (rom.data.info)", "rom.data.info")
        if info is not None:
            (self.out_dir / "data_info.json").write_text(json.dumps(_jsonable(info), indent=2))
        yield self.call("status (battery, network)", "rom.data.status")
        behaviors = yield self.call("behavior list", "rom.optional.behavior.info")
        if behaviors is not None:
            (self.out_dir / "behaviors.json").write_text(json.dumps(_jsonable(behaviors), indent=2))
        for modality in (
            "actuator.motor",
            "actuator.light",
            "actuator.audio",
            "sensor.sight",
            "sensor.hearing",
            "sensor.touch",
            "sensor.proprio",
        ):
            yield self.call(f"{modality} info", f"rom.{modality}.info")
        frames = yield self.call("joint angles now (proprio.read)", "rom.sensor.proprio.read")
        if frames:
            (self.out_dir / "proprio.json").write_text(json.dumps(_jsonable(frames), indent=2))
        yield self.call("keyword (STT) info", "rie.dialogue.keyword.info")

    @inlineCallbacks
    def speech(self) -> Any:
        yield self.call("set language en", "rie.dialogue.config.language", lang="en")
        for i in range(3):
            yield self.call(
                f"say #{i + 1} (returns when done)",
                "rie.dialogue.say",
                text=SAY_TEXT,
                note="LISTEN: the robot should say the test sentence" if i == 0 else "",
            )
        yield self.call(
            "say_animated",
            "rie.dialogue.say_animated",
            text="And now I move while I talk!",
            note="WATCH: the robot should talk AND gesture",
        )

    @inlineCallbacks
    def lights(self) -> Any:
        yield self.call(
            "eyes green->red->blue",
            "rom.actuator.light.write",
            mode="linear",
            frames=[
                {"time": 1000, "data": {"body.head.eyes": [0, 255, 0]}},
                {"time": 2000, "data": {"body.head.eyes": [255, 0, 0]}},
                {"time": 3000, "data": {"body.head.eyes": [0, 0, 255]}},
            ],
            note="WATCH: the eyes should fade green -> red -> blue",
        )
        yield self.call(
            "left eye only (white)",
            "rom.actuator.light.write",
            frames=[{"time": 500, "data": {"body.head.eyes.left": [255, 255, 255]}}],
            note="WATCH: only the LEFT eye should turn white",
        )
        yield self.call("light stop", "rom.actuator.light.stop")

    @inlineCallbacks
    def audio(self) -> Any:
        yield self.call("volume (read)", "rom.actuator.audio.volume")
        pcm = _beep_pcm(rate=44100, seconds=1.0, freq=440)
        yield self.call(
            "play raw PCM beep (44.1k stereo)",
            "rom.actuator.audio.play",
            data=pcm,
            rate=44100,
            note="LISTEN: a 1-second 440 Hz beep (raw PCM, no WAV header)",
        )
        yield self.call(
            "play WAV-file beep (44.1k stereo)",
            "rom.actuator.audio.play",
            data=_wav_bytes(pcm, rate=44100),
            rate=44100,
            note="LISTEN: the same beep again, this time sent as a full WAV file",
        )
        pcm24 = _beep_pcm(rate=24000, seconds=1.0, freq=660)
        yield self.call(
            "play raw PCM beep (24k = tts-1 rate)",
            "rom.actuator.audio.play",
            data=pcm24,
            rate=24000,
            note="LISTEN: a higher beep at 24 kHz, the rate OpenAI tts-1 PCM uses",
        )

    @inlineCallbacks
    def motion(self) -> Any:
        if self.skip_motion:
            _out("\n(skipping motion checks: --skip-motion)")
            return
        yield self.call(
            "behavior BlocklyStand",
            "rom.optional.behavior.play",
            name="BlocklyStand",
            note="WATCH: the robot stands up",
        )
        yield self.call(
            "behavior BlocklyWaveRightArm",
            "rom.optional.behavior.play",
            name="BlocklyWaveRightArm",
            note="WATCH: the robot waves its right arm",
        )
        yield self.call(
            "behavior BlocklyShrug",
            "rom.optional.behavior.play",
            name="BlocklyShrug",
            note="WATCH: the robot shrugs",
        )
        yield self.call(
            "custom pose: head nod (motor.write)",
            "rom.actuator.motor.write",
            force=True,
            frames=[
                {"time": 400, "data": {"body.head.pitch": 0.1}},
                {"time": 1200, "data": {"body.head.pitch": -0.1}},
                {"time": 2000, "data": {"body.head.pitch": 0.1}},
                {"time": 2400, "data": {"body.head.pitch": 0.0}},
            ],
            note="WATCH: a custom head nod built from raw motor frames",
        )

    @inlineCallbacks
    def camera(self) -> Any:
        frames = yield self.call("camera frame (sight.read)", "rom.sensor.sight.read")
        if not frames:
            return
        frame = frames[0] if isinstance(frames, list) else frames
        data = frame.get("data", {}) if isinstance(frame, dict) else {}
        _out(f"       frame keys: {list(data)}")
        for ubi, value in data.items():
            if isinstance(value, (bytes, bytearray)):
                self.save_bytes(f"camera_{ubi}{_image_ext(bytes(value))}", bytes(value))

    @inlineCallbacks
    def hearing(self) -> Any:
        chunks: list[bytes] = []
        first_chunk_at: list[float] = []

        def on_audio(frame: dict[str, Any]) -> None:
            body = frame.get("data", {}).get("body.head.front", b"")
            if body and not first_chunk_at:
                first_chunk_at.append(time.perf_counter())
            chunks.append(bytes(body))

        _out(f"\n>>> SPEAK: recording the robot microphone for {HEARING_S:.0f} s ...")
        yield self.session.subscribe(on_audio, "rom.sensor.hearing.stream")
        start = time.perf_counter()
        yield self.call("hearing stream open", "rom.sensor.hearing.stream")
        yield sleep(HEARING_S)
        yield self.call("hearing stream close", "rom.sensor.hearing.close")
        raw = b"".join(chunks)
        record: dict[str, Any] = {
            "label": "microphone capture",
            "chunks": len(chunks),
            "bytes": len(raw),
            "ok": bool(raw),
        }
        if first_chunk_at:
            record["first_chunk_ms"] = round((first_chunk_at[0] - start) * 1000)
        if raw:
            # Example code says 16 kHz mono int16; samples/s here lets us check that claim.
            record["samples_per_s_if_int16"] = round(len(raw) / 2 / HEARING_S)
            self.save_bytes("mic.wav", _wav_bytes(raw, rate=16000, channels=1))
        _out(
            f"[{'OK  ' if raw else 'FAIL'}] microphone capture                 "
            f"{len(chunks)} chunks, {len(raw)} bytes"
        )
        self.results.append(record)


# -- small pure helpers ----------------------------------------------------------------------


def _beep_pcm(rate: int, seconds: float, freq: float) -> bytes:
    """Stereo int16 sine beep with short fades so it does not click."""
    n = int(rate * seconds)
    fade = int(rate * 0.02)
    out = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        s = int(12000 * env * math.sin(2 * math.pi * freq * i / rate))
        out += struct.pack("<hh", s, s)
    return bytes(out)


def _wav_bytes(pcm: bytes, rate: int, channels: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _image_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    return ".bin"


def _summarise(value: Any) -> Any:
    """Keep results readable: replace bytes by their length, cap long lists."""
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {str(k): _summarise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_summarise(v) for v in value[:20]]
        return items + [f"... {len(value) - 20} more"] if len(value) > 20 else items
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _load_realm(cli_realm: str | None) -> str:
    if cli_realm:
        return cli_realm
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    except ImportError:
        pass
    realm = os.environ.get("RIDK_REALM", "").strip()
    if not realm:
        sys.exit(
            "No realm. Pass --realm rie.XXXX or set RIDK_REALM in .env "
            "(portal -> robot -> hamburger menu -> clipboard)."
        )
    return realm


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--realm", help="robot realm, e.g. rie.5e1312363dbf49eed032e123")
    parser.add_argument("--skip-motion", action="store_true", help="do not move the robot")
    parser.add_argument("--out", type=Path, help="output folder (default logs/ridk_probe/...)")
    args = parser.parse_args(argv)

    realm = _load_realm(args.realm)
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = args.out or repo_root / "logs" / "ridk_probe" / datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    _out(f"Connecting to {WAMP_URL}, realm {realm}\nResults go to {out_dir}\n")

    @inlineCallbacks
    def on_join(session: Any, details: Any) -> Any:
        probe = Probe(session, out_dir, args.skip_motion)
        try:
            yield probe.wait_cloud_modules()
            for step in (
                probe.info,
                probe.speech,
                probe.lights,
                probe.audio,
                probe.motion,
                probe.camera,
                probe.hearing,
            ):
                yield step()
        finally:
            summary = {
                "realm": realm,
                "when": datetime.now().isoformat(timespec="seconds"),
                "results": probe.results,
            }
            (out_dir / "results.json").write_text(json.dumps(_jsonable(summary), indent=2))
            ok = sum(1 for r in probe.results if r.get("ok"))
            _out(
                f"\nDone: {ok}/{len(probe.results)} checks OK. Full results: "
                f"{out_dir / 'results.json'}"
            )
            session.leave()

    wamp = Component(
        transports=[{"url": WAMP_URL, "serializers": ["msgpack"], "max_retries": 0}],
        realm=realm,
    )
    wamp.on_join(on_join)
    run([wamp], log_level="warn")


if __name__ == "__main__":
    main()
