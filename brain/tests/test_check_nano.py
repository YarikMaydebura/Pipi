"""The check_nano tool's offline parts (it never calls the API in tests)."""

from __future__ import annotations

import struct
import zlib

import pytest

from pipi_brain.tools.check_nano import main, red_png


def test_red_png_is_a_valid_png() -> None:
    png = red_png(4)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (4, 4)
    idat_len = struct.unpack(">I", png[33:37])[0]
    pixels = zlib.decompress(png[41 : 41 + idat_len])
    assert pixels[1:4] == b"\xff\x00\x00"


def test_missing_key_stops_before_any_call(
    tmp_config_dir, no_env_secrets: None, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_config_dir / "dev.yaml"
    cfg.write_text("extends: base.yaml\nmode: dev\n", encoding="utf-8")
    assert main(["--config", str(cfg)]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
